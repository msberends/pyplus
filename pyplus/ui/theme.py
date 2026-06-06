"""Design tokens and global CSS. Call apply_theme() once per page."""

from __future__ import annotations

from nicegui import ui

_GOOGLE_FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">'
)

# ── Design tokens + component styles ──────────────────────────────────────────
_CSS = """
/* ─── Design tokens ─────────────────────────────────────────────────────── */
:root {
  /* Brand — use green-dark for interactive elements (sufficient contrast) */
  --c-brand:          #80bd1d;   /* PLUS green-light — accent, positive */
  --c-brand-dark:     #227647;   /* PLUS green-dark — buttons, focus */
  --c-brand-tint:     #f0f7e6;
  --c-brand-tint-2:   #dff0c0;
  --c-danger:         #e3131d;   /* PLUS red — destructive only */
  --c-danger-tint:    #fff0f0;
  --c-accent:         #554da7;   /* PLUS purple — highlight */

  /* Neutrals */
  --c-bg:             #f5f7fa;
  --c-surface:        #ffffff;
  --c-surface-2:      #f9fafb;
  --c-border:         #e5e8ef;
  --c-border-strong:  #cfd4de;

  /* Text — text-3/text-4 darkened to meet WCAG AA (4.5:1) on white at small sizes */
  --c-text:    #0f1923;
  --c-text-2:  #374151;
  --c-text-3:  #5b6470;   /* ~6.0:1 */
  --c-text-4:  #6b7280;   /* ~4.8:1 — lightest text that still passes AA */

  /* Shadows */
  --shadow-xs: 0 1px 2px rgba(0,0,0,.05);
  --shadow-sm: 0 1px 4px rgba(0,0,0,.07), 0 1px 2px rgba(0,0,0,.04);
  --shadow-md: 0 4px 16px rgba(0,0,0,.08), 0 2px 6px rgba(0,0,0,.04);
  --shadow-lg: 0 12px 40px rgba(0,0,0,.10), 0 4px 16px rgba(0,0,0,.06);
  --shadow-xl: 0 24px 64px rgba(0,0,0,.12), 0 8px 24px rgba(0,0,0,.06);

  /* Border radius */
  --r-xs:   3px;
  --r-sm:   6px;
  --r-md:   10px;
  --r-lg:   16px;
  --r-xl:   20px;
  --r-2xl:  28px;
  --r-full: 9999px;

  /* Typography */
  --font:  'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --t-xs:  11px;
  --t-sm:  13px;
  --t-base:14px;
  --t-md:  15px;
  --t-lg:  17px;
  --t-xl:  20px;
  --t-2xl: 24px;
  --t-3xl: 30px;

  /* Weights */
  --w-normal:   400;
  --w-medium:   500;
  --w-semibold: 600;
  --w-bold:     700;
  --w-extrabold:800;

  /* Motion */
  --ease:     cubic-bezier(.4, 0, .2, 1);
  --ease-out: cubic-bezier(0, 0, .2, 1);
  --dur-fast: 120ms;
  --dur-base: 200ms;
  --dur-slow: 320ms;
}

/* ─── Base ───────────────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; }

body {
  font-family: var(--font);
  font-size: var(--t-base);
  color: var(--c-text);
  background: var(--c-bg);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  margin: 0;
  padding: 0;
}

/* Remove Quasar page padding — pages manage their own layout */
.q-page { padding: 0 !important; }
.q-page-container { padding-top: 0 !important; }

/* ─── Scrollbar ──────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: var(--c-border-strong);
  border-radius: var(--r-full);
}
::-webkit-scrollbar-thumb:hover { background: var(--c-text-4); }

/* ─── Focus ring ─────────────────────────────────────────────────────────── */
:focus-visible {
  outline: 2px solid var(--c-brand-dark);
  outline-offset: 2px;
  border-radius: var(--r-xs);
}

/* ─── Skeleton shimmer ───────────────────────────────────────────────────── */
@keyframes shimmer {
  0%   { background-position: -600px 0; }
  100% { background-position: 600px 0; }
}
.skeleton {
  background: linear-gradient(
    90deg,
    var(--c-border) 25%,
    var(--c-surface-2) 50%,
    var(--c-border) 75%
  );
  background-size: 1200px 100%;
  animation: shimmer 1.5s ease-in-out infinite;
  border-radius: var(--r-sm);
}

/* ─── Quasar field overrides ─────────────────────────────────────────────── */
.q-field--outlined .q-field__control {
  border-radius: var(--r-md) !important;
}
.q-field--outlined .q-field__control::before {
  border-color: var(--c-border) !important;
  transition: border-color var(--dur-fast) var(--ease) !important;
}
.q-field--outlined .q-field__control:hover::before {
  border-color: var(--c-border-strong) !important;
}
.q-field--outlined.q-field--focused .q-field__control::before {
  border-color: var(--c-brand-dark) !important;
  border-width: 2px !important;
}
.q-field__label { font-weight: var(--w-medium) !important; }

/* ─── Quasar button overrides ────────────────────────────────────────────── */
.q-btn {
  font-weight: var(--w-semibold) !important;
  letter-spacing: 0.02em !important;
  transition: all var(--dur-fast) var(--ease) !important;
}
.q-btn--rounded { border-radius: var(--r-md) !important; }
.q-btn:not([disabled]):hover { filter: brightness(1.05); }
.q-btn:not([disabled]):active { transform: scale(.98); }

/* ─── Quasar checkbox ────────────────────────────────────────────────────── */
.q-checkbox__label { font-size: var(--t-base) !important; }

/* ─── Quasar notification (quiet toasts) ─────────────────────────────────── */
.q-notification {
  border-radius: var(--r-lg) !important;
  font-size: var(--t-sm) !important;
  font-weight: var(--w-medium) !important;
  box-shadow: var(--shadow-lg) !important;
}

/* ─── Login page ─────────────────────────────────────────────────────────── */
.sp-login-bg {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  background:
    radial-gradient(ellipse 60% 40% at 15% 15%, rgba(128,189,29,.08) 0%, transparent 55%),
    radial-gradient(ellipse 50% 40% at 85% 85%, rgba(34,118,71,.06) 0%, transparent 55%),
    var(--c-bg);
}

.sp-login-card {
  width: 100%;
  max-width: 420px;
  background: var(--c-surface);
  border-radius: var(--r-2xl);
  box-shadow: var(--shadow-xl);
  padding: 2.25rem 2.25rem 1.75rem;
  display: flex;
  flex-direction: column;
}

.sp-login-logo-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 1.75rem;
}

.sp-login-logo-mark {
  width: 38px;
  height: 38px;
  background: linear-gradient(145deg, #80bd1d 0%, #227647 100%);
  border-radius: var(--r-md);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 2px 10px rgba(34,118,71,.30);
}
.sp-login-logo-mark span {
  font-size: 13px;
  font-weight: 800;
  color: white;
  letter-spacing: -0.5px;
  line-height: 1;
}
.sp-login-logo-name {
  font-size: 18px !important;
  font-weight: 700 !important;
  color: var(--c-text) !important;
  letter-spacing: -0.3px;
  line-height: 1 !important;
}

.sp-login-heading {
  font-size: var(--t-2xl) !important;
  font-weight: var(--w-bold) !important;
  color: var(--c-text) !important;
  letter-spacing: -.4px;
  line-height: 1.2 !important;
  margin: 0 !important;
  padding: 0 !important;
}
.sp-login-subheading {
  font-size: var(--t-sm) !important;
  color: var(--c-text-3) !important;
  margin: .3rem 0 1.5rem !important;
  line-height: 1.4 !important;
}

.sp-login-fields {
  display: flex;
  flex-direction: column;
  gap: .6rem;
  width: 100%;
}
.sp-login-field { width: 100%; }

.sp-login-remember { margin: .4rem 0; }

.sp-login-btn {
  width: 100%;
  height: 48px !important;
  font-size: var(--t-md) !important;
  margin-top: .6rem;
  border-radius: var(--r-md) !important;
}

.sp-login-progress {
  display: flex;
  flex-direction: column;
  gap: .45rem;
  margin-top: .8rem;
  min-height: 36px;
}
.sp-login-progress-label {
  font-size: var(--t-sm) !important;
  color: var(--c-text-3) !important;
  text-align: center;
}

/* ─── Availability badges ────────────────────────────────────────────────── */
.sp-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: var(--r-full);
  font-size: var(--t-xs);
  font-weight: var(--w-semibold);
  letter-spacing: .02em;
}
.sp-badge-available  { background: var(--c-brand-tint);  color: #1a5e22; }
.sp-badge-unavailable{ background: var(--c-danger-tint); color: #b91c1c; }
.sp-badge-stale      { background: #fffbeb;               color: #92400e; }

/* ─── Product card ───────────────────────────────────────────────────────── */
.sp-product-card {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg);
  overflow: hidden;
  transition: box-shadow var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease);
}
.sp-product-card:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--c-border-strong);
}

/* ─── Qty stepper ────────────────────────────────────────────────────────── */
.sp-qty {
  display: inline-flex;
  align-items: center;
  border: 1.5px solid var(--c-border);
  border-radius: var(--r-full);
  overflow: hidden;
  background: var(--c-surface);
}
.sp-qty-btn {
  width: 36px; height: 36px;
  display: flex; align-items: center; justify-content: center;
  background: none; border: none; padding: 0; margin: 0;
  font: inherit; cursor: pointer; user-select: none;
  color: var(--c-text-2);
  font-size: 18px; font-weight: var(--w-bold);
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}
.sp-qty-btn:hover { background: var(--c-brand-tint); color: var(--c-brand-dark); }
.sp-qty-btn:active { transform: scale(.92); }
.sp-qty-count {
  min-width: 28px; text-align: center;
  font-size: var(--t-md); font-weight: var(--w-semibold);
}

/* ─── Promo ribbon ───────────────────────────────────────────────────────── */
.sp-promo-ribbon {
  background: var(--c-brand);
  color: white;
  font-size: var(--t-xs);
  font-weight: var(--w-bold);
  padding: 3px 8px;
  border-radius: var(--r-sm);
  letter-spacing: .03em;
  text-transform: uppercase;
}

/* Category group header — for grouped cart + staples views. */
.sp-cat-header {
  font-size: 10px;
  font-weight: var(--w-bold);
  color: var(--c-text-4);
  letter-spacing: .08em;
  text-transform: uppercase;
  padding: .5rem 0 .2rem;
  margin-top: .25rem;
  border-bottom: 1px solid var(--c-border);
  display: block;
}
.sp-cat-header:first-child { margin-top: 0; }

/* Compact "on offer" tag — for cart + staples rows. */
.sp-promo-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  background: var(--c-brand);
  color: white;
  font-size: 9px;
  font-weight: var(--w-bold);
  padding: 1px 6px;
  border-radius: var(--r-xs);
  letter-spacing: .02em;
  text-transform: uppercase;
  white-space: nowrap;
}

/* ─── Lane error state ───────────────────────────────────────────────────── */
.sp-lane-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 1.5rem 1rem;
  gap: .5rem;
  text-align: center;
}

/* ─── Cart icon bump animation (mobile add-to-cart feedback) ─────────────── */
@keyframes sp-cart-bump {
  0%   { transform: scale(1); }
  40%  { transform: scale(1.22); }
  100% { transform: scale(1); }
}
.sp-cart-bump {
  /* Spring-like easing: slight overshoot for a satisfying "pop" feel */
  animation: sp-cart-bump 230ms cubic-bezier(0.34, 1.56, 0.64, 1);
}

/* ─── Lane container ─────────────────────────────────────────────────────── */
.sp-lane {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-xl);
  overflow: hidden;
}
.sp-lane-header {
  padding: 1rem 1.25rem .75rem;
  border-bottom: 1px solid var(--c-border);
}
.sp-lane-title {
  font-size: var(--t-lg) !important;
  font-weight: var(--w-bold) !important;
  color: var(--c-text) !important;
  letter-spacing: -.2px;
}
.sp-lane-subtitle {
  font-size: var(--t-xs) !important;
  color: var(--c-text-3) !important;
  margin-top: 1px;
}
.sp-lane-body { padding: .75rem; }

/* ─── Cart panel ─────────────────────────────────────────────────────────── */
.sp-cart-panel {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-xl);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: sticky;
  top: 0;  /* the cart column supplies the 1.25rem top inset (aligns with the lanes) */
  max-height: calc(100vh - 2.5rem);
}
.sp-cart-header {
  padding: 1rem 1.25rem .75rem;
  border-bottom: 1px solid var(--c-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-shrink: 0;
}
.sp-cart-title {
  font-size: var(--t-lg) !important;
  font-weight: var(--w-bold) !important;
  color: var(--c-text) !important;
}
.sp-cart-body {
  flex: 1;
  overflow-y: auto;
  padding: .5rem .75rem;
}
.sp-cart-footer {
  padding: .75rem 1rem;
  border-top: 1px solid var(--c-border);
  flex-shrink: 0;
}
.sp-cart-total {
  font-size: var(--t-xl) !important;
  font-weight: var(--w-bold) !important;
  color: var(--c-text) !important;
}
.sp-cart-savings {
  font-size: var(--t-sm) !important;
  color: var(--c-brand-dark) !important;
  font-weight: var(--w-semibold) !important;
}
/* Promotional-discount banner in the cart footer — green, tag-led, so the
   discount reads as savings on offers (matches the Aanbiedingen palette). */
.sp-cart-savings-banner {
  display: flex;
  align-items: center;
  gap: .375rem;
  margin-bottom: .5rem;
  padding: .4rem .625rem;
  background: var(--c-brand-tint);
  border-radius: var(--r-md);
  color: var(--c-brand-dark);
}
.sp-cart-savings-banner .sp-cart-savings { font-weight: var(--w-bold) !important; }
.sp-cart-savings-from {
  font-size: var(--t-xs) !important;
  color: var(--c-brand-dark) !important;
  opacity: .7;
}
/* Statiegeld line in the cart footer — neutral (grey), since the deposit is a
   cost already counted in the total, not a saving. Deliberately *not* the green
   korting language, so the two read as distinct. */
.sp-cart-deposit-line {
  display: flex;
  align-items: center;
  gap: .375rem;
  margin-bottom: .5rem;
  padding: .4rem .625rem;
  background: var(--c-surface-2);
  border-radius: var(--r-md);
  font-size: var(--t-sm);
  color: var(--c-text-3);
}
.sp-cart-deposit-amount {
  font-weight: var(--w-bold) !important;
  color: var(--c-text) !important;
}
.sp-cart-deposit-note {
  font-size: var(--t-xs) !important;
  color: var(--c-text-3) !important;
  opacity: .7;
}
/* Mobile bottom-bar discount pill — same green language, compact. */
.sp-bar-savings {
  margin-left: auto;
  font-size: 11px !important;
  font-weight: var(--w-bold) !important;
  color: var(--c-brand-dark) !important;
  background: var(--c-brand-tint);
  padding: 2px 8px;
  border-radius: var(--r-full);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

/* ─── Dish card ──────────────────────────────────────────────────────────── */
.sp-dish-card {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-lg);
  padding: .875rem 1rem;
  transition: box-shadow var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease);
  cursor: pointer;
}
.sp-dish-card:hover {
  box-shadow: var(--shadow-sm);
  border-color: var(--c-border-strong);
}
.sp-dish-card-name {
  font-size: var(--t-md) !important;
  font-weight: var(--w-semibold) !important;
  color: var(--c-text) !important;
}

/* ─── Suggestion chip ────────────────────────────────────────────────────── */
.sp-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--c-brand-tint);
  border: 1px solid var(--c-brand-tint-2);
  border-radius: var(--r-full);
  font-size: var(--t-sm);
  font-weight: var(--w-medium);
  color: var(--c-brand-dark);
}

/* ─── Aggregation summary panel ──────────────────────────────────────────── */
.sp-agg-panel {
  background: var(--c-brand-tint);
  border: 1px solid var(--c-brand-tint-2);
  border-radius: var(--r-lg);
  padding: .875rem 1rem;
}
.sp-agg-saving {
  font-size: var(--t-sm) !important;
  font-weight: var(--w-semibold) !important;
  color: var(--c-brand-dark) !important;
}

/* ─── Cockpit layout ─────────────────────────────────────────────────────── */
.sp-cockpit-root {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: var(--c-bg);
}

/* Left nav rail */
.sp-nav-rail {
  width: 68px;
  flex-shrink: 0;
  background: var(--c-surface);
  border-right: 1px solid var(--c-border);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: .75rem 0;
  gap: .25rem;
  z-index: 10;
}
.sp-nav-logo {
  width: 36px; height: 36px;
  background: linear-gradient(145deg, #80bd1d 0%, #227647 100%);
  border-radius: var(--r-md);
  display: flex; align-items: center; justify-content: center;
  margin-bottom: .75rem;
  box-shadow: 0 2px 8px rgba(34,118,71,.25);
  flex-shrink: 0;
}
.sp-nav-btn {
  width: 44px; height: 44px;
  border-radius: var(--r-md);
  display: flex; align-items: center; justify-content: center;
  color: var(--c-text-3);
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
  text-decoration: none;
}
.sp-nav-btn:hover { background: var(--c-brand-tint); color: var(--c-brand-dark); }
.sp-nav-btn.active { background: var(--c-brand-tint-2); color: var(--c-brand-dark); }
.sp-nav-spacer { flex: 1; }

/* Main stage — 2 columns, sized so each column = cart width (3 equal visual lanes) */
.sp-cockpit-stage {
  flex: 2 1 0;
  min-width: 0;
  overflow-y: auto;
  padding: 1.25rem;
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: auto auto;
  gap: 1rem;
  align-content: start;
}

/* Cart column — 1 part of the 3-part layout (stage takes 2 parts).
   Mirrors the stage's padding so the cart panel lines up as a third lane;
   no own border/background — the panel card supplies its own chrome. */
.sp-cockpit-cart-col {
  flex: 1 1 0;
  min-width: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  padding: 1.25rem;
  padding-left: 0;
}

/* Full-width content area for dishes/settings (fills all space after nav rail) */
.sp-page-content {
  overflow-y: auto;
  padding: 1.5rem;
  background: var(--c-bg);
  width: calc(100vw - 68px);
}

/* Cart item row */
.sp-cart-item {
  display: flex; align-items: center; gap: .625rem;
  padding: .5rem 0;
  border-bottom: 1px solid var(--c-border-subtle, #f1f3f7);
}
.sp-cart-item:last-child { border-bottom: none; }
/* On-offer rows: green tint + a green accent rail (matches the korting banner /
   Aanbiedingen palette) so the products responsible for the discount stand out. */
.sp-cart-item.sp-cart-item-promo {
  background: var(--c-brand-tint);
  border-radius: var(--r-sm);
  border-bottom-color: transparent;
  box-shadow: inset 3px 0 0 0 var(--c-brand);
  padding-left: .5rem;
  padding-right: .5rem;
}
.sp-cart-item-img {
  width: 44px; height: 44px;
  border-radius: var(--r-sm);
  object-fit: contain;
  background: var(--c-surface-2);
  flex-shrink: 0;
}
.sp-cart-item-name {
  font-size: var(--t-sm) !important;
  font-weight: var(--w-medium) !important;
  color: var(--c-text) !important;
  line-height: 1.3;
}
.sp-cart-item-unit {
  font-size: var(--t-xs) !important;
  color: var(--c-text-3) !important;
}
.sp-cart-item-right { margin-left: auto; text-align: right; flex-shrink: 0; }
.sp-cart-item-price {
  font-size: var(--t-sm) !important;
  font-weight: var(--w-semibold) !important;
  color: var(--c-text) !important;
}
.sp-cart-item-qty { font-size: var(--t-xs) !important; color: var(--c-text-3) !important; }

/* Cart footer */
.sp-cart-total-row {
  display: flex; align-items: center; justify-content: space-between;
  padding: .625rem 0 .375rem;
}
.sp-checkout-btn { width: 100%; margin-top: .5rem; }

/* Lane placeholder */
.sp-lane-placeholder {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; padding: 2rem 1rem; gap: .5rem;
  color: var(--c-text-4); text-align: center;
}
.sp-lane-placeholder-icon { font-size: 2rem; line-height: 1; opacity: .4; }

/* ─── Dishes ─────────────────────────────────────────────────────────────── */
.sp-dish-card {
  background: var(--c-surface);
  border: 1px solid var(--c-border);
  border-radius: var(--r-xl);
  padding: 1.125rem 1.25rem;
  transition: box-shadow var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease);
  cursor: pointer;
  display: flex;
  flex-direction: column;
}
.sp-dish-card:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--c-border-strong);
}
.sp-dish-card-name {
  font-size: var(--t-md) !important;
  font-weight: var(--w-semibold) !important;
  color: var(--c-text) !important;
  line-height: 1.3;
}
.sp-editor-dialog .q-dialog__inner { padding: 1rem; }
@media (max-width: 600px) {
  /* Full-height editor on phones so the body scrolls and the pinned
     footer (add-ingredient) stays on screen. */
  .sp-editor-dialog .q-dialog__inner { padding: 0; }
  .sp-editor-dialog .q-card {
    width: 100vw !important;
    max-width: 100vw !important;
    height: 100dvh !important;
    max-height: 100dvh !important;
    border-radius: 0 !important;
  }
}

/* ─── Staples lane ───────────────────────────────────────────────────────── */
.sp-staples-body {
  padding: .375rem .625rem .75rem;
  overflow-y: auto;
  max-height: 42vh;
}

.sp-staples-item {
  display: flex;
  align-items: center;
  gap: .5rem;
  padding: .3125rem 0;
  border-bottom: 1px solid var(--c-border);
  min-height: 40px;
}
.sp-staples-item:last-child { border-bottom: none; }

.sp-avail-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--c-border-strong);
}
.sp-avail-dot-ok  { background: var(--c-brand); }
.sp-avail-dot-no  { background: var(--c-danger); }

/* ─── Deals lane ─────────────────────────────────────────────────────────── */
.sp-deals-body {
  padding: .375rem .625rem .75rem;
  overflow-y: auto;
  max-height: 42vh;
}

.sp-promo-card {
  padding: .5rem 0;
  border-bottom: 1px solid var(--c-border);
}
.sp-promo-card:last-child { border-bottom: none; }

.sp-promo-img {
  width: 52px; height: 52px;
  border-radius: var(--r-sm);
  object-fit: contain;
  background: var(--c-surface-2);
  flex-shrink: 0;
}

.sp-promo-products {
  margin-top: .375rem;
  border-top: 1px solid var(--c-border);
  padding-top: .25rem;
}

.sp-promo-banner {
  display: flex;
  align-items: center;
  gap: .375rem;
  padding: .375rem .5rem;
  background: var(--c-brand-tint);
  border-radius: var(--r-sm);
  margin: .25rem 0;
}

/* ─── Meals lane ─────────────────────────────────────────────────────────── */
.sp-meals-body {
  padding: .625rem .75rem .75rem;
  overflow-y: auto;
  max-height: 42vh;
}

.sp-meals-slot {
  display: flex;
  align-items: center;
  gap: .5rem;
  padding: .2rem 0;
  min-height: 40px;
}

.sp-meals-day {
  width: 34px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: .2rem .25rem;
  background: var(--c-surface-2);
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm);
  min-height: 34px;
}

.sp-meals-chip {
  flex: 1;
  display: flex;
  align-items: center;
  gap: .375rem;
  padding: .3rem .5rem .3rem .625rem;
  background: var(--c-brand-tint);
  border: 1.5px solid var(--c-brand-tint-2);
  border-radius: var(--r-md);
  min-width: 0;
  min-height: 34px;
  transition: background var(--dur-fast) var(--ease);
}
.sp-meals-chip:hover { background: var(--c-brand-tint-2); }

.sp-meals-picker .q-field__control { height: 36px !important; min-height: 36px !important; }
.sp-meals-picker .q-field__label {
  font-size: 12px !important;
  color: var(--c-text-4) !important;
  top: 8px !important;
}

/* ─── Search lane ────────────────────────────────────────────────────────── */
.sp-search-result {
  display: flex;
  align-items: center;
  gap: .625rem;
  padding: .5rem .125rem;
  border-bottom: 1px solid var(--c-border);
  transition: background var(--dur-fast) var(--ease);
}
.sp-search-result:last-child { border-bottom: none; }
.sp-search-result:hover { background: var(--c-surface-2); border-radius: var(--r-sm); }

.sp-search-img {
  width: 44px; height: 44px;
  border-radius: var(--r-sm);
  object-fit: contain;
  background: var(--c-surface-2);
  flex-shrink: 0;
}
.sp-search-info {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
.sp-search-name {
  font-size: var(--t-sm) !important;
  font-weight: var(--w-medium) !important;
  color: var(--c-text) !important;
  line-height: 1.3;
}
.sp-search-unit {
  font-size: var(--t-xs) !important;
  color: var(--c-text-3) !important;
}
.sp-search-price {
  font-size: var(--t-sm) !important;
  font-weight: var(--w-semibold) !important;
  color: var(--c-text) !important;
}
.sp-search-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex-shrink: 0;
}
.sp-search-add-btn {
  width: 36px; height: 36px;
  border-radius: var(--r-full);
  background: var(--c-brand-tint);
  border: 1.5px solid var(--c-brand-tint-2);
  display: flex; align-items: center; justify-content: center;
  padding: 0; cursor: pointer;
  transition: background var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease);
}
.sp-search-add-btn:hover { background: var(--c-brand-tint-2); transform: scale(1.08); }
.sp-search-add-btn:active { transform: scale(.94); }

/* Syncing stepper state */
.sp-qty--syncing {
  opacity: .65;
  pointer-events: none;
}
/* Give the rounded stepper border-radius (the canonical .sp-qty-btn rule lives
   in the Qty stepper section above; this only adds the corner shaping). */
.sp-qty-btn { border-radius: var(--r-xs); }

/* Mobile cart bottom bar */
.sp-mobile-cart-bar {
  display: none;
  position: fixed;
  bottom: 0; left: 0; right: 0;
  height: 58px;
  background: var(--c-surface);
  border-top: 1px solid var(--c-border);
  padding: 0 1rem;
  align-items: center;
  gap: .625rem;
  z-index: 200;
  cursor: pointer;
  box-shadow: 0 -4px 16px rgba(0,0,0,.08);
  transition: box-shadow var(--dur-base) var(--ease);
}
.sp-mobile-cart-bar:active { background: var(--c-surface-2); }

/* Mobile */
@media (max-width: 768px) {
  .sp-cockpit-root { flex-direction: column; height: auto; overflow: visible; }
  .sp-nav-rail {
    width: 100%; height: 58px; flex-direction: row;
    justify-content: space-around; border-right: none;
    border-top: 1px solid var(--c-border); order: 3; padding: 0 .5rem;
    position: fixed; bottom: 0; left: 0; right: 0; z-index: 100;
    background: var(--c-surface);
  }
  .sp-nav-logo { display: none; }
  .sp-nav-spacer { display: none; }
  .sp-cockpit-stage {
    flex: 1 1 auto;
    grid-template-columns: 1fr; order: 1;
    padding-bottom: calc(58px + 58px + 1.25rem);  /* nav + cart bar */
    overflow-y: auto;
  }
  .sp-cockpit-cart-col { display: none; }  /* replaced by bottom bar */
  /* In the mobile cart sheet the dialog card is the frame, so the panel fills
     it edge-to-edge with no second border/radius and no sticky/height cap. */
  .sp-cart-panel {
    flex: 1;
    width: 100%;
    min-width: 0;  /* let content clip/wrap instead of widening the panel off-screen */
    border: none;
    border-radius: 0;
    position: static;
    max-height: none;
  }
  .sp-page-content { width: 100%; padding-bottom: calc(58px + 1.25rem); }  /* nav bar */
  .sp-deals-body, .sp-meals-body, .sp-staples-body { max-height: none; overflow-y: visible; }
  .sp-mobile-cart-bar { display: flex; bottom: 58px; }
}
"""


def apply_theme() -> None:
    """Inject Inter font, design tokens, and all component CSS into the current page."""
    ui.add_head_html(_GOOGLE_FONTS, shared=True)
    ui.add_css(_CSS, shared=True)  # shared=True → injected once for all pages
    ui.colors(
        primary="#227647",  # PLUS green-dark — main interactive colour
        secondary="#80bd1d",  # PLUS green-light — accent
        accent="#554da7",  # PLUS purple
        negative="#e3131d",  # PLUS red
        positive="#16a34a",
        info="#3b82f6",
        warning="#d97706",
    )
