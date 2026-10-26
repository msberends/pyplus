"""Organic-alternative UI — the "Bio" chip and its swap dialogs (cart, staples, dishes)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable

from nicegui import ui

from pyplus.i18n import t
from pyplus.ui.components.swap import swap_product_row

if TYPE_CHECKING:
    from plus.models import Product


@dataclass
class OrganicSwap:
    """One proposed swap: the current product (qty × price) → its organic equivalent."""

    sku: str
    name: str
    image: str
    subtitle: str
    price: float  # per unit
    qty: int
    alt: Product

    @property
    def diff(self) -> float:
        return round((self.alt.price - self.price) * self.qty, 2)


def _eur(amount: float) -> str:
    return f"{abs(amount):.2f}".replace(".", ",")


def diff_label(diff: float) -> str:
    """'€ 0,40 duurder' / '€ 0,10 goedkoper' / 'Zelfde prijs'."""
    if abs(diff) < 0.005:
        return t("organic.same")
    return t("organic.more" if diff > 0 else "organic.less", amount=_eur(diff))


def organic_chip(alt: Product, on_click: Callable[[], None]) -> None:
    """Small 'Bio' chip that opens the swap for `alt`."""
    with (
        ui.element("div")
        .classes("sp-organic-chip")
        .on("click.stop", lambda _: on_click())
        .tooltip(t("organic.chip_tip", name=alt.name))
    ):
        ui.icon("sym_r_eco", size="12px")
        ui.label(t("organic.chip"))


def _swap_rows(s: OrganicSwap) -> None:
    swap_product_row(
        t("organic.current"),
        s.image,
        s.name,
        s.subtitle,
        s.qty,
        s.price,
        s.price * s.qty,
        highlight=False,
    )
    ui.icon("sym_r_south", size="16px").style("color:var(--c-text-4);align-self:center")
    swap_product_row(
        t("organic.suggested"),
        s.alt.image_url,
        s.alt.name,
        s.alt.subtitle,
        s.qty,
        s.alt.price,
        s.alt.price * s.qty,
        highlight=True,
    )


def _diff_line(diff: float, text: str | None = None) -> ui.label:
    with ui.element("div").style("display:flex;align-items:center;gap:.25rem"):
        ui.icon("sym_r_eco", size="14px").style("color:var(--c-brand-dark)")
        return ui.label(text or diff_label(diff)).style(
            "font-size:12px;font-weight:700;color:var(--c-brand-dark)"
        )


def _dialog_header(title: str, dlg) -> None:
    with ui.element("div").style(
        "display:flex;align-items:center;justify-content:space-between;"
        "padding:.875rem 1rem;border-bottom:1px solid var(--c-border)"
    ):
        ui.label(title).style("font-size:16px;font-weight:700;color:var(--c-text)")
        ui.button(icon="sym_r_close", on_click=dlg.close).props(
            "flat round dense size=sm color=grey"
        )


def show_organic_swap_dialog(s: OrganicSwap, on_confirm: Callable[[], Awaitable[None]]) -> None:
    """Confirm one swap to the organic equivalent; `on_confirm` performs it."""
    with ui.dialog(value=True) as dlg:
        with ui.card().style(
            "min-width:300px;max-width:420px;width:100%;padding:0;overflow:hidden;"
            "align-items:stretch"
        ):
            _dialog_header(t("organic.title"), dlg)
            with ui.element("div").style(
                "padding:.75rem 1rem;display:flex;flex-direction:column;gap:.5rem"
            ):
                _swap_rows(s)
                with ui.element("div").style("align-self:center;margin-top:.125rem"):
                    _diff_line(s.diff)
            with ui.element("div").style(
                "display:flex;justify-content:flex-end;gap:.5rem;"
                "padding:.75rem 1rem;border-top:1px solid var(--c-border)"
            ):
                ui.button(t("action.cancel"), on_click=dlg.close).props("flat rounded no-caps")

                async def _confirm() -> None:
                    dlg.close()
                    await on_confirm()

                ui.button(t("organic.replace"), on_click=_confirm).props(
                    "unelevated rounded no-caps color=primary"
                )


def show_organic_bulk_dialog(
    swaps: list[OrganicSwap], on_apply: Callable[[OrganicSwap], Awaitable[None]]
) -> None:
    """List every available organic swap, each applicable on its own or all at once."""
    swaps = list(swaps)
    total_lbl: list[ui.label] = []

    def _total_text() -> str:
        return t("organic.bulk_total", diff=diff_label(sum(s.diff for s in swaps)))

    with ui.dialog(value=True) as dlg:
        with ui.card().style(
            "min-width:300px;max-width:440px;width:100%;padding:0;overflow:hidden;"
            "align-items:stretch"
        ):
            _dialog_header(t("organic.bulk_title"), dlg)
            with ui.element("div").style("padding:.5rem 1rem;max-height:60vh;overflow-y:auto"):
                for s in swaps:
                    with ui.element("div").style(
                        "display:flex;flex-direction:column;gap:.375rem;padding:.625rem 0;"
                        "border-bottom:1px solid var(--c-border)"
                    ) as block:
                        _swap_rows(s)
                        with ui.element("div").style(
                            "display:flex;align-items:center;gap:.5rem;margin-top:.125rem"
                        ):
                            with ui.element("div").style("flex:1"):
                                _diff_line(s.diff)

                            async def _one(snap=s, b=block) -> None:
                                b.delete()
                                swaps.remove(snap)
                                if not swaps:
                                    dlg.close()
                                elif total_lbl:
                                    total_lbl[0].set_text(_total_text())
                                await on_apply(snap)

                            ui.button(t("organic.replace"), on_click=_one).props(
                                "flat dense no-caps size=sm color=primary"
                            ).style("flex-shrink:0")

            with ui.element("div").style(
                "display:flex;align-items:center;gap:.5rem;padding:.75rem 1rem;"
                "border-top:1px solid var(--c-border)"
            ):
                with ui.element("div").style("flex:1"):
                    total_lbl.append(_diff_line(0.0, _total_text()))

                async def _all() -> None:
                    dlg.close()
                    for snap in list(swaps):
                        await on_apply(snap)

                ui.button(t("organic.replace_all"), icon="sym_r_done_all", on_click=_all).props(
                    "unelevated rounded no-caps color=primary size=sm"
                )
