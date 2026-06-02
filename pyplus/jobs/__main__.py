"""
PyPLUS job runner CLI.

Usage:
    uv run python -m pyplus.jobs <job_name> [--user all|<id>]

Examples:
    uv run python -m pyplus.jobs full_preload --user all
    uv run python -m pyplus.jobs refresh_promotions --user 1
    uv run python -m pyplus.jobs refresh_orders --user all

Jobs that call PLUS (all except recompute_ml) require stored remember-me
credentials.  Users without them are skipped with a warning.

Exit codes: 0 = all done, 1 = at least one user failed.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pyplus.jobs")

_PLUS_JOBS = {
    "refresh_promotions",
    "refresh_purchase_catalogue",
    "refresh_orders",
    "refresh_products",
    "refresh_product_catalogue",
    "full_preload",
    "weekly_ntfy",
}
_NO_CLIENT_JOBS = {"recompute_ml"}
_ALL_JOBS = _PLUS_JOBS | _NO_CLIENT_JOBS


async def _run_job_for_user(job_name: str, user) -> bool:
    """Login, run the named job, close.  Returns True on success."""
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal
    from pyplus.security.secrets import decrypt

    if job_name in _NO_CLIENT_JOBS:
        from pyplus.jobs import registry

        job_fn = getattr(registry, job_name)
        await job_fn(user_id=user.id)
        return True

    async with AsyncSessionLocal() as db:
        creds = await repo.get_credentials(db, user.id)

    if not creds:
        log.warning("user=%d has no stored credentials — skipping", user.id)
        return True  # not a failure; just not applicable

    email = decrypt(user.plus_email_enc)
    password = decrypt(creds.password_enc)
    if not email or not password:
        log.error("user=%d credentials could not be decrypted — skipping", user.id)
        return False

    from plus.client import PlusClient

    async with PlusClient(headless=True) as client:
        ok = await client.login(email, password)
        if not ok:
            log.error("user=%d login failed", user.id)
            return False
        await client.get_session_state()
        store = user.store_number or client._session.store_number or 0

        from pyplus.jobs import registry

        job_fn = getattr(registry, job_name)

        kwargs: dict = {"user_id": user.id}
        import inspect

        sig = inspect.signature(job_fn)
        if "client" in sig.parameters:
            kwargs["client"] = client
        if "store_number" in sig.parameters:
            kwargs["store_number"] = store

        await job_fn(**kwargs)
    return True


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="PyPLUS background job runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("job", choices=sorted(_ALL_JOBS), help="Which job to run")
    parser.add_argument(
        "--user",
        default="all",
        help="User ID to run for, or 'all' for every user with credentials (default: all)",
    )
    args = parser.parse_args()

    # Init DB (run migrations if needed)
    from pyplus.db.engine import init_db

    await init_db()

    # Resolve target users
    from pyplus.db import repo
    from pyplus.db.engine import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        if args.user == "all":
            users = await repo.get_users_with_credentials(db)
            if not users:
                log.warning("No users with stored credentials found — nothing to do")
                return 0
        else:
            try:
                uid = int(args.user)
            except ValueError:
                log.error("--user must be 'all' or an integer user ID, got: %r", args.user)
                return 1
            user = await repo.get_user_by_id(db, uid)
            if not user:
                log.error("User %d not found in database", uid)
                return 1
            users = [user]

    log.info("Running '%s' for %d user(s)", args.job, len(users))

    failures = 0
    for user in users:
        log.info("── user=%d (%s) ──", user.id, user.display_name or "?")
        try:
            success = await _run_job_for_user(args.job, user)
            if not success:
                failures += 1
        except Exception as exc:
            log.exception("user=%d job=%s crashed: %s", user.id, args.job, exc)
            failures += 1

    if failures:
        log.error("%d/%d user(s) failed", failures, len(users))
        return 1

    log.info("Done — all %d user(s) OK", len(users))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
