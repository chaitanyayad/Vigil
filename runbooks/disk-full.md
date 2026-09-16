# Disk Full

Filesystem usage approaching 100%.

## Symptoms
- `disk_pct` above threshold, or climbing much faster than the organic baseline
- Writes failing, databases switching read-only, log agents dropping data

## Diagnose
1. `df -h` — which mount is filling?
2. `du -xh --max-depth=2 /path | sort -h | tail -20` — where's the growth?
3. Usual suspects: runaway logs, core dumps, tmp files, database WAL,
   docker images/volumes (`docker system df`).
4. `lsof +L1` — deleted-but-open files still holding space.

## Mitigate
- Rotate/compress or truncate runaway logs (`logrotate --force`, `truncate -s 0` for
  actively-held files).
- Clear package/image caches: `docker system prune`, apt/yum caches.
- Grow the volume if the usage is legitimate.
- Restart processes holding deleted files to release the space.

## Verify
- Usage back under threshold with headroom (>15% free).
- Add/adjust retention so the same directory doesn't refill.
