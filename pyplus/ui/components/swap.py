"""Shared row for swap dialogs (cheaper pack, organic alternative)."""

from __future__ import annotations

from nicegui import ui

from pyplus.ui.format import alt_text as _alt
from pyplus.ui.format import thumbnail_url


def swap_product_row(
    label: str,
    image: str,
    name: str,
    subtitle: str,
    qty: int,
    unit_price: float,
    total: float,
    highlight: bool,
) -> None:
    """One product row in a swap dialog — formatted like a staples/promo row:
    image · name + subtitle · quantity × unit price + total."""
    border = "var(--c-brand)" if highlight else "var(--c-border)"
    with ui.element("div").style(
        "display:flex;align-items:center;gap:.625rem;padding:.5rem .625rem;"
        f"border:1px solid {border};border-radius:var(--r-sm)"
    ):
        if image:
            ui.image(thumbnail_url(image, 44)).style(
                "width:44px;height:44px;object-fit:contain;border-radius:var(--r-sm);"
                "background:var(--c-surface-2);flex-shrink:0"
            ).props(f'alt="{_alt(name)}"')
        else:
            ui.element("div").style(
                "width:44px;height:44px;border-radius:var(--r-sm);"
                "background:var(--c-border);flex-shrink:0"
            )
        with ui.element("div").style("flex:1;min-width:0;overflow:hidden"):
            ui.label(label).style(
                "font-size:10px;font-weight:600;text-transform:uppercase;"
                "letter-spacing:.03em;color:var(--c-text-4)"
            )
            ui.label(name).style(
                "font-size:13px;font-weight:600;color:var(--c-text);line-height:1.3;"
                "overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
            )
            if subtitle:
                ui.label(subtitle).style("font-size:11px;color:var(--c-text-3);line-height:1.2")
        with ui.element("div").style(
            "display:flex;flex-direction:column;align-items:flex-end;flex-shrink:0"
        ):
            ui.label(f"{qty}× € {unit_price:.2f}".replace(".", ",")).style(
                "font-size:10px;color:var(--c-text-4)"
            )
            ui.label(f"€ {total:.2f}".replace(".", ",")).style(
                "font-size:14px;font-weight:700;color:var(--c-text)"
            )
