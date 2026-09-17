"""VIGIL orchestrator app factory + background workers.

Background work (all in-process, no Celery — see docs/adr/0005):
  - heartbeat watchdog          every 10 s
  - ML inference tick           every 60 s
  - ledger batch + anchor tick  every 60 s (interval/size policy inside)
  - auto-triage of criticals    every 30 s
  - nightly retrain             02:00 UTC
"""

import asyncio
import contextlib
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vigil import __version__
from vigil.api import alerts, auth, health, ingest, ledger, metrics, ml, observers, rules
from vigil.db.session import dispose_engine, get_sessionmaker
from vigil.ledger.batcher import ledger_tick
from vigil.ml.service import inference_tick, nightly_retrain
from vigil.triage.runbooks import index_runbooks
from vigil.triage.service import auto_triage_tick
from vigil.workers.watchdog import watchdog_loop
from vigil.ws import live
from vigil.ws.bus import close_redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


def create_app(enable_workers: bool = True) -> FastAPI:
    app = FastAPI(title="VIGIL", version=__version__)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # dev dashboard; tighten for a real deployment
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router in (auth, health, observers, ingest, metrics, rules, alerts, ledger, ml):
        app.include_router(router.router)
    app.include_router(live.router)

    if enable_workers:
        _wire_workers(app)

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await close_redis()
        await dispose_engine()

    return app


def _wire_workers(app: FastAPI) -> None:
    stop = asyncio.Event()
    scheduler = AsyncIOScheduler()

    @app.on_event("startup")
    async def startup() -> None:
        try:
            async with get_sessionmaker()() as db:
                await index_runbooks(db)
        except Exception:
            log.exception("runbook indexing failed (continuing)")
        app.state.watchdog = asyncio.create_task(watchdog_loop(stop))
        scheduler.add_job(inference_tick, IntervalTrigger(seconds=60), max_instances=1)
        scheduler.add_job(ledger_tick, IntervalTrigger(seconds=60), max_instances=1)
        scheduler.add_job(auto_triage_tick, IntervalTrigger(seconds=30), max_instances=1)
        scheduler.add_job(nightly_retrain, CronTrigger(hour=2, minute=0))
        scheduler.start()
        log.info("workers started")

    @app.on_event("shutdown")
    async def stop_workers() -> None:
        stop.set()
        scheduler.shutdown(wait=False)
        task = getattr(app.state, "watchdog", None)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = create_app()
