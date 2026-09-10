"""Baseline: extensions, all tables, metrics hypertable, metrics_1m continuous
aggregate, retention policies.

Revision ID: 0001
Revises: None
"""

from alembic import op

from vigil.db.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    bind = op.get_bind()
    Base.metadata.create_all(bind)

    op.execute(
        "SELECT create_hypertable('metrics', 'ts', if_not_exists => TRUE, "
        "chunk_time_interval => INTERVAL '1 day')"
    )

    # Continuous aggregate + policies can't run inside a transaction
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_1m
            WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
            SELECT time_bucket('1 minute', ts) AS bucket,
                   observer_id,
                   avg(cpu_pct)    AS cpu_avg,   max(cpu_pct)  AS cpu_max,
                   avg(mem_pct)    AS mem_avg,   max(mem_pct)  AS mem_max,
                   avg(disk_pct)   AS disk_avg,  max(disk_pct) AS disk_max,
                   avg(net_rx_bps) AS net_rx_avg,
                   avg(net_tx_bps) AS net_tx_avg,
                   avg(load1)      AS load1_avg, max(load1)    AS load1_max,
                   count(*)        AS sample_count
            FROM metrics
            GROUP BY 1, 2
            WITH NO DATA
        """)
        op.execute("""
            SELECT add_continuous_aggregate_policy('metrics_1m',
                start_offset => INTERVAL '2 hours',
                end_offset => INTERVAL '1 minute',
                schedule_interval => INTERVAL '1 minute',
                if_not_exists => TRUE)
        """)
        # Raw samples: 7 days. 1-minute aggregate: 90 days.
        op.execute("SELECT add_retention_policy('metrics', INTERVAL '7 days', if_not_exists => TRUE)")
        op.execute(
            "SELECT add_retention_policy('metrics_1m', INTERVAL '90 days', if_not_exists => TRUE)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP MATERIALIZED VIEW IF EXISTS metrics_1m CASCADE")
    Base.metadata.drop_all(op.get_bind())
