"""
APScheduler in-app scheduler — registers named jobs to run on a schedule.

Disabled when PYPLUS_DISABLE_SCHEDULER=1 (operators who run everything via cron).
Jobs are exactly the same functions as in registry.py; APScheduler just drives them.
"""

from __future__ import annotations

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


def start_scheduler() -> None:
    global _scheduler
    from pyplus.config import settings

    if settings.disable_scheduler:
        log.info("In-app scheduler disabled (PYPLUS_DISABLE_SCHEDULER=1)")
        return
    if not settings.secret_key:
        log.info("No PYPLUS_SECRET_KEY — in-app scheduler disabled (no stored credentials)")
        return

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger

    _scheduler = AsyncIOScheduler(timezone="Europe/Amsterdam")

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

    _scheduler.start()
    log.info(
        "APScheduler started — full_preload at 02:30, weekly_ntfy Thursdays at 07:00 Amsterdam"
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
