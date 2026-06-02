#!/usr/bin/env bash
# PyPLUS — crontab reference
#
# Copy relevant lines into `crontab -e` after filling in <APP_DIR>.
# Ensure the process environment includes PYPLUS_SECRET_KEY
# (e.g. source the .env file or add it directly to the cron environment).
#
# Prerequisites:
#   • uv is installed and on PATH (or use the full path, e.g. /home/<user>/.local/bin/uv)
#   • PYPLUS_SECRET_KEY is set in the environment (required for credential decryption)
#   • Users have opted in to "Onthoud mij" (remember-me) in the app
#   • Playwright browsers are installed: uv run playwright install chromium
#
# Jobs that call PLUS.nl require a logged-in browser session and therefore
# need stored remember-me credentials. Users without them are skipped.
# Only recompute_ml runs without credentials.
#
# Tip: if you prefer cron over the in-app APScheduler, set:
#   PYPLUS_DISABLE_SCHEDULER=1  in <APP_DIR>/.env
# This prevents double-scheduling without disabling the in-app scheduler entirely.
#
# ── Environment ────────────────────────────────────────────────────────────────
# Cron does not source .env automatically. Either:
#   a) Add env vars at the top of your crontab:
#      PYPLUS_SECRET_KEY=<your-key>
#      PYPLUS_DATA_DIR=<DATA_DIR>
#
#   b) Or load them via a wrapper:
#      30 2 * * *  set -a; . <APP_DIR>/.env; set +a; cd <APP_DIR> && ...
#
# ── Recommended schedule ───────────────────────────────────────────────────────
#
# Run full_preload nightly at 02:30 (Amsterdam time) for all users.
# This warms: purchase catalogue, order history, promotions, product availability.
# After these run, recompute_ml scores the ML models from the warmed caches.
#
# 30 2 * * *  cd <APP_DIR> && uv run python -m pyplus.jobs full_preload --user all >> <APP_DIR>/logs/preload.log 2>&1
#
# ── Or run jobs individually ───────────────────────────────────────────────────
#
# Order history — daily, off-peak (incremental; only fetches new orders)
# 0 3 * * *   cd <APP_DIR> && uv run python -m pyplus.jobs refresh_orders --user all >> <APP_DIR>/logs/orders.log 2>&1
#
# Purchase catalogue — daily (static breadth signal for ML)
# 15 3 * * *  cd <APP_DIR> && uv run python -m pyplus.jobs refresh_purchase_catalogue --user all >> <APP_DIR>/logs/catalogue.log 2>&1
#
# Promotions — daily; run again Thursday morning when next-week deals publish
# 30 3 * * *  cd <APP_DIR> && uv run python -m pyplus.jobs refresh_promotions --user all >> <APP_DIR>/logs/promotions.log 2>&1
# 0  7 * * 4  cd <APP_DIR> && uv run python -m pyplus.jobs refresh_promotions --user all >> <APP_DIR>/logs/promotions.log 2>&1
#
# Product availability — processes ALL dish/staple SKUs (no cap), sorted oldest-checked first.
# Runtime scales with SKU count: ~1 API call/SKU; ~200 SKUs ≈ 3-5 min.
# Products not found at the store are automatically marked unavailable.
# 45 3 * * *  cd <APP_DIR> && uv run python -m pyplus.jobs refresh_products --user all >> <APP_DIR>/logs/products.log 2>&1
#
# ML recompute — after all refresh jobs (no PLUS call needed)
# 30 4 * * *  cd <APP_DIR> && uv run python -m pyplus.jobs recompute_ml --user all >> <APP_DIR>/logs/ml.log 2>&1
#
# Weekly ntfy alert — Thursday morning when deals publish.
# Run 15 min after refresh_promotions so the cache is warm.
# weekly_ntfy will fetch next-week promos itself if the cache is cold.
# 15 7 * * 4  cd <APP_DIR> && uv run python -m pyplus.jobs weekly_ntfy --user all >> <APP_DIR>/logs/ntfy.log 2>&1
#
# ── Log rotation ───────────────────────────────────────────────────────────────
# Add a weekly log rotation to prevent unbounded growth:
# 0 5 * * 0   find <APP_DIR>/logs -name '*.log' -mtime +30 -delete
#
# ── One-liner to rotate and run full preload ───────────────────────────────────
# 30 2 * * *  mkdir -p <APP_DIR>/logs && cd <APP_DIR> && uv run python -m pyplus.jobs full_preload --user all >> <APP_DIR>/logs/preload.log 2>&1
