"""Shared accessible controls.

Steppers and add-to-cart buttons were previously clickable ``<div>``s — not
keyboard-focusable and unnamed for screen readers. These helpers render real
``<button>`` elements with an ``aria-label`` and ``type=button``, so they get
keyboard activation (Enter/Space), the global ``:focus-visible`` ring, and a
proper accessible name for free. Styling comes from the existing ``.sp-qty-btn``
and ``.sp-search-add-btn`` classes (see ``theme.py``).
"""

from __future__ import annotations

from typing import Callable

from nicegui import ui


def stepper_button(symbol: str, *, aria_label: str, on_click: Callable, font_size: str = "15px"):
    """A square −/+ stepper button. `on_click` is attached as the click handler."""
    btn = (
        ui.element("button")
        .classes("sp-qty-btn")
        .props(f'type=button aria-label="{aria_label}"')
        .on("click", on_click)
    )
    with btn:
        ui.label(symbol).style(
            f"font-size:{font_size};font-weight:700;line-height:1;pointer-events:none"
        )
    return btn


def add_button(*, aria_label: str, on_click: Callable, font_size: str = "18px"):
    """The round green "+" add-to-cart button. `on_click` is the click handler."""
    btn = (
        ui.element("button")
        .classes("sp-search-add-btn")
        .props(f'type=button aria-label="{aria_label}"')
        .on("click", on_click)
    )
    with btn:
        ui.label("+").style(
            f"font-size:{font_size};font-weight:700;color:var(--c-brand-dark);"
            "line-height:1;pointer-events:none"
        )
    return btn
