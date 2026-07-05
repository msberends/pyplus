"""
APScheduler in-app scheduler — registers named jobs to run on a schedule.

Disabled when PYPLUS_DISABLE_SCHEDULER=1 (operators who run everything via cron).
Jobs are exactly the same functions as in registry.py; APScheduler just drives them.
"""

from __future__ import annotations

import datetime
import logging

log = logging.getLogger(__name__)

_scheduler = None


async def _login_and_run(job_fn, user_id: int, store_number: int) -> None:
    """Create a PlusClient, log in with stored credentials, run the job, clean up."""
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.security.secrets import decrypt

    async with AsyncSessionLocal() as db:
        creds = await repo.get_credentials(db, user_id)
        user = await repo.get_user_by_id(db, user_id)

    if not creds or not user:
        log.warning("[scheduler] user=%d has no stored credentials — skipping", user_id)
        return

    email_plain = decrypt(user.plus_email_enc)
    password_plain = decrypt(creds.password_enc)
    if not email_plain or not password_plain:
        log.warning("[scheduler] user=%d credentials could not be decrypted — skipping", user_id)
        return

    from plus.client import PlusClient

    async with PlusClient(headless=True) as client:
        ok = await client.login(email_plain, password_plain)
        if not ok:
            log.error("[scheduler] user=%d login failed — skipping job", user_id)
            return
        await client.get_session_state()

        await job_fn(
            user_id=user_id,
            client=client,
            store_number=store_number,
        )


async def _run_weekly_ntfy_all_users() -> None:
    """APScheduler entry point: weekly ntfy alert for every user with stored credentials."""
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        users = await repo.get_users_with_credentials(db)

    if not users:
        log.info("[scheduler] no users with credentials — skipping weekly_ntfy")
        return

    from pyplus.jobs.registry import weekly_ntfy

    for user in users:
        if user.store_number is None:
            continue
        try:
            await _login_and_run(weekly_ntfy, user.id, user.store_number)
        except Exception as exc:
            log.error("[scheduler] weekly_ntfy for user=%d failed: %s", user.id, exc)


async def _run_catalogue_all_users() -> None:
    """APScheduler entry point: weekly full-catalogue sync per distinct store."""
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.jobs.registry import refresh_product_catalogue

    async with AsyncSessionLocal() as db:
        users = await repo.get_users_with_credentials(db)

    if not users:
        log.info("[scheduler] no users with credentials — skipping catalogue sync")
        return

    # One sync per store is enough (product_cache is store-scoped); dedupe stores.
    seen_stores: set[int] = set()
    for user in users:
        if user.store_number is None or user.store_number in seen_stores:
            continue
        seen_stores.add(user.store_number)
        try:
            await _login_and_run(refresh_product_catalogue, user.id, user.store_number)
        except Exception as exc:
            log.error("[scheduler] catalogue sync for store=%d failed: %s", user.store_number, exc)


async def _run_full_preload_all_users() -> None:
    """APScheduler entry point: full preload for every user with stored credentials."""
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        users = await repo.get_users_with_credentials(db)

    if not users:
        log.info("[scheduler] no users with credentials — nothing to preload")
        return

    from pyplus.jobs.registry import full_preload

    for user in users:
        if user.store_number is None:
            continue
        try:
            await _login_and_run(full_preload, user.id, user.store_number)
        except Exception as exc:
            log.error("[scheduler] full_preload for user=%d failed: %s", user.id, exc)


# Abandoned interactive sessions (and their Playwright browsers) are reaped after
# this much idle time. Activity = navigation or any cart mutation.
_SESSION_MAX_IDLE_SECONDS = 2 * 3600


async def _reap_idle_sessions() -> None:
    """Scheduler entry point: close interactive sessions idle beyond the threshold."""
    from pyplus.session import manager

    try:
        n = await manager.reap_idle(_SESSION_MAX_IDLE_SECONDS)
        if n:
            log.info("[scheduler] reaped %d idle session(s)", n)
    except Exception as exc:
        log.error("[scheduler] session reaper failed: %s", exc)


async def _run_weather_all_users() -> None:
    """APScheduler entry point: daily weather fetch for every user with weather enabled."""
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.jobs.registry import refresh_weather

    async with AsyncSessionLocal() as db:
        users = await repo.get_users_with_credentials(db)

    for user in users:
        try:
            await refresh_weather(user_id=user.id)
        except Exception as exc:
            log.error("[scheduler] weather for user=%d failed: %s", user.id, exc)


def start_scheduler() -> None:
    global _scheduler
    from pyplus.config import settings

    if settings.disable_scheduler:
        log.info("In-app scheduler disabled (PYPLUS_DISABLE_SCHEDULER=1)")
        return

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    _scheduler = AsyncIOScheduler(timezone="Europe/Amsterdam")

    # Idle-session reaper — independent of credentials; frees abandoned browsers.
    _scheduler.add_job(
        _reap_idle_sessions,
        IntervalTrigger(minutes=15),
        id="session_reaper",
        replace_existing=True,
        misfire_grace_time=300,
    )

    if not settings.secret_key:
        # Without a key there are no stored credentials, so the cache-warming jobs
        # can't log in — but the session reaper still runs.
        _scheduler.start()
        log.info("No PYPLUS_SECRET_KEY — only the idle-session reaper is scheduled")
        return

    # Full preload nightly at 02:30
    _scheduler.add_job(
        _run_full_preload_all_users,
        CronTrigger(hour=2, minute=30),
        id="full_preload_nightly",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Weekly ntfy alert every Thursday at 07:00 (when next-week PLUS deals publish)
    _scheduler.add_job(
        _run_weekly_ntfy_all_users,
        CronTrigger(day_of_week="thu", hour=7, minute=0),
        id="weekly_ntfy_thursday",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Catalogue sync Fri–Mon at 02:15 — covers new promo products (live Thursday
    # night) through the main shopping window. Heavy (~5–7 min download).
    _scheduler.add_job(
        _run_catalogue_all_users,
        CronTrigger(day_of_week="fri,sat,sun,mon", hour=2, minute=15),
        id="catalogue_weekly",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    # Weather runs at 02:30 alongside the nightly preload (it's fast, no PLUS auth needed)
    _scheduler.add_job(
        _run_weather_all_users,
        CronTrigger(hour=2, minute=30),
        id="weather_daily",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.start()
    log.info(
        "APScheduler started — full_preload + weather at 02:30, "
        "catalogue Fri–Mon at 02:15, weekly_ntfy Thursdays at 07:00 Amsterdam"
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def scheduler_next_runs() -> dict[str, "datetime.datetime"]:
    """Map ``job_id → next_run_time`` for the active in-app scheduler.

    Returns an empty dict when the scheduler is disabled or not running, which the
    Settings page uses to decide whether to show "next run" countdowns at all.
    """
    if _scheduler is None or not getattr(_scheduler, "running", False):
        return {}
    runs: dict[str, datetime.datetime] = {}
    for job in _scheduler.get_jobs():
        if job.next_run_time is not None:
            runs[job.id] = job.next_run_time
    return runs
