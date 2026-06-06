# Code Review: pyplus

## Summary

PyPLUS is a well-architected personal grocery app. The separation of concerns is genuinely good: the reverse-engineered `plus/` client is isolated, all DB access is funnelled through `pyplus/db/repo.py` and consistently scoped by `user_id`, the cache-warming jobs are idempotent and lock-protected, and the "fast-open" doctrine (render from DB caches, revalidate quietly) is followed in most lanes. SQL is fully parameterised through SQLAlchemy — no injection surface. The optimistic cart with server-version reconciliation is correct and matches the documented invariants.

The remaining issues are concentrated in **UI accessibility** and a few **security hardening** gaps, not data integrity:

1. **Interactive controls are non-accessible `<div>`s** (steppers, add buttons) — not keyboard-focusable, no ARIA, and most are below the 44×44px touch-target minimum. The whole add-to-cart flow is unusable by keyboard/screen-reader and fiddly on mobile.
2. **Low-contrast hint text** fails WCAG AA across the app.
3. A handful of **defence-in-depth gaps** (HTTP security headers, exception text in the UI).

Top recommendation: make the steppers real `<button>`s with proper sizing and labels.

> The **Performance & Responsiveness** findings from the original review have been implemented and removed from this document (idle-session reaper + close-on-overwrite, login concurrency cap, FTS5 search, debounced/gated cart side-effects, parallelised meals loads, N+1 upsert fixes, hot-path logging). One item was intentionally **not** changed and is kept below.

---

## Performance & Responsiveness

### Low

#### `clear_all` / "apply all savings" are necessarily serial but slow on big carts
- **File(s):** `pyplus/services/cart.py:79-111`, `pyplus/ui/components/cart.py:552-561`
- **Issue:** Each removal/swap is a sequential ~400 ms PLUS call (required by `CheckoutVersion` optimistic locking). A 20-item clear is ~8 s with no per-row progress.
- **Status:** **Left as-is by design.** The serial order is mandatory (optimistic locking), and the UI already clears optimistically/instantly so there is no real latency to hide. A "opschonen…" affordance could be added later but is cosmetic.

---

## Security

> All **High** and **Medium** security findings from the original review have been implemented and removed from this document: login concurrency cap (`asyncio.Semaphore`), SSRF guard on the user-controlled ntfy URL (`pyplus/security/net.py`, enforced in `_test_ntfy` and `weekly_ntfy`), email masking in logs, HKDF-derived per-purpose subkeys for credential encryption / cookie signing / iCal HMAC (with legacy-decrypt and legacy-token fallbacks so existing data and calendar subscriptions keep working), HTTP security-header middleware, generic (non-leaking) UI error messages, and the captured-payload diagnostic moved to `log.debug`. One **Low** item is partly addressed and kept below.

### Low

#### iCal token cannot be rotated per-user
- **File(s):** `pyplus/security/tokens.py`
- **Status:** **Partly addressed.** The token now uses an HKDF-derived key separate from the encryption/cookie keys (the original key-reuse concern is fixed). What remains is purely a feature gap: there is still no way to revoke a single leaked subscription URL short of rotating `PYPLUS_SECRET_KEY`. Exposure is low (4 weeks of dish names, unforgeable).
- **Fix (deferred):** Add a per-user random salt (e.g. in `UserSettings`) folded into the HMAC input, plus a "regenerate calendar link" button, to allow independent rotation.

---

## User Interface

> The **Critical**, **High**, and **Medium** UI findings have been implemented and removed from this document: the stepper/add controls are now real `<button>` elements (shared `ui/components/controls.py`) with `aria-label`s (`i18n` `a11y.*` keys), so they are keyboard-focusable, screen-reader-named, and pick up the `:focus-visible` ring; the duplicate `.sp-qty-btn` CSS rule is consolidated and the controls enlarged to 36px; `--c-text-3/4` darkened to pass WCAG AA on white; product images across the shopping lanes carry sanitized `alt` text; the settings grid uses `minmax(min(380px,100%),1fr)`; the mobile cart bar truncates its savings label; and confirm/store dialogs autofocus their safe action.
>
> Note on target size: controls are 36px, which clears WCAG 2.2 AA (SC 2.5.8, 24px) comfortably; the original review cited the 44px AAA/Apple HIG figure, which is not met (44px would bloat the dense cockpit layout). One **Low** item is left as a deferred nicety below.

### Low

#### Login progress is a single indeterminate bar for ~20 s
- **File(s):** `pyplus/ui/pages/login.py`
- **Issue:** Two text states ("Inloggen bij PLUS…", "Winkelwagen ophalen…") across a long wait; can feel stalled.
- **Status:** **Left as-is.** The two messages already map to the two genuinely long phases; the ~20 s wait is a single opaque Playwright OAuth call (S1) that can't be subdivided into real milestones, so finer-grained text would be fictional. A rotating set of reassurance messages on a timer could be added later, but it's cosmetic.

---

## Additional Observations

- **Schema is migration-only (no `create_all`).** `init_db` (`db/engine.py:47-66`) runs Alembic to head and nothing else, so every model in `db/models.py` must have a corresponding migration or its table won't exist at runtime. Worth a CI check that `alembic upgrade head` then a metadata-diff is empty, to catch a model added without a migration.
- **`expire_on_commit=False` + long-lived ORM objects.** Fine given the read-mostly pattern, but be careful passing detached ORM rows into UI closures that later re-read attributes — prefer the Pydantic/dataclass DTOs you already use in `plus/models.py`.
- **Test coverage gap.** Good offline suites exist for services/ml/format/exports, but there are **no tests for the cart reconciliation logic** (`services/cart.py` — optimistic apply, rollback, image-preserve patch) or the session/auth guards, and the `plus` client is only exercised by manual scripts. The reconcile/rollback path is the riskiest untested code (it mutates the authoritative cart view). Add unit tests with a faked `client.add_to_cart_api` returning canned checkouts, covering success, failure-rollback, and the debounce coalescing in `CartService._queue`.
- **`__import__("sqlalchemy").delete(...)`** in `repo.py:842` is a code smell — import `delete` at module top like the rest. Same for the inline `import json as _json` scattered through `repo.py`/`deals.py`; hoist them.
- **`print` vs `logging` inconsistency** across `plus/client.py` (print) and the rest of the app (logging) makes log levels unmanageable in production.
- **Dependencies are floor-pinned (`>=`)** in `pyproject.toml`; the `uv.lock` is the real pin, which is the right setup. Consider a periodic `uv lock --upgrade` + advisory scan (e.g. `pip-audit`/`osv-scanner`) in CI, since `nicegui`, `playwright`, and `cryptography` are all security-relevant and the floors (`nicegui>=2.0.0`) are broad.
- **`UserSession.client` typed as `object`** to dodge a circular import (`user_session.py:18`); a `TYPE_CHECKING`-guarded import would restore type safety without the runtime cycle.
