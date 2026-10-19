"""Ask TypeSafe's Jev whether the current fare is the best this trip will see."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from typesafe_sdk import Noul, SystemOneResponse, TypeSafeClient

from .models import Quote

DEFAULT_DROP_PCT = 5.0  # a fall smaller than this isn't worth the risk of waiting
WAIT_THRESHOLD = 0.5  # wait when a meaningful drop is more likely than not


class SystemOneClient(Protocol):
    def system_one(self, state: Any, questions: Any, **kwargs: Any) -> SystemOneResponse: ...


@dataclass
class Advice:
    p_best_now: float  # probability no lower fare appears before departure
    p_meaningful_drop: float  # probability the fare falls to `drop_target` or below
    drop_target: float
    drop_pct: float
    recommendation: str  # "book now" or "wait"
    model: str = ""

    @property
    def p_future_better(self) -> float:
        return 1.0 - self.p_best_now


def build_state(quote: Quote) -> dict[str, Any]:
    """Facts Jev reasons over. Arithmetic is done here so the model only has to judge."""
    trip = quote.trip
    days_out = (trip.depart - quote.as_of).days
    history = sorted(quote.history, key=lambda p: p.observed)
    state: dict[str, Any] = {
        "trip": {
            "origin": trip.origin,
            "destination": trip.destination,
            "depart": trip.depart.isoformat(),
            "return_date": trip.return_date.isoformat() if trip.return_date else None,
            "round_trip": trip.round_trip,
            "cabin": trip.cabin,
            "adults": trip.adults,
            "traveler_notes": trip.notes or None,
        },
        "quote": {
            "as_of": quote.as_of.isoformat(),
            "days_until_departure": days_out,
            "current_price": quote.current_price,
            "currency": trip.currency,
            "cheapest_itinerary": quote.itinerary or None,
            "provider_price_level": quote.provider_level,
            "source": quote.source or None,
        },
        "price_history": [{"date": p.observed.isoformat(), "price": p.price} for p in history],
    }
    if quote.typical_range:
        low, high = quote.typical_range
        state["quote"]["typical_price_range"] = {"low": low, "high": high}
        if high > low:
            state["quote"]["position_in_typical_range_pct"] = round(100 * (quote.current_price - low) / (high - low), 1)
    if history:
        lowest = min(p.price for p in history)
        state["price_history_summary"] = {
            "observations": len(history),
            "lowest_seen": lowest,
            "highest_seen": max(p.price for p in history),
            "current_vs_lowest_seen_pct": round(100 * (quote.current_price - lowest) / lowest, 1) if lowest else None,
            "change_since_first_observation": round(quote.current_price - history[0].price, 2),
        }
    return state


def build_questions(quote: Quote, drop_target: float, drop_pct: float) -> dict[str, Noul]:
    currency = quote.trip.currency
    context = (
        "Consider the `price_history`, the `quote.typical_price_range` and `quote.provider_price_level`, "
        "`quote.days_until_departure`, and how fares for this kind of route and cabin usually move as "
        "departure approaches."
    )
    return {
        "best_now": Noul(
            instructions=(
                f"{context} Will `quote.current_price` turn out to be the lowest fare offered for this trip "
                "at any point from `quote.as_of` until departure?"
            ),
            criteria={
                "true": "No fare lower than the current price is offered for this trip before departure.",
                "false": "At some point before departure, a fare lower than the current price is offered.",
            },
        ),
        "meaningful_drop": Noul(
            instructions=(
                f"{context} Will the fare for this trip fall to {drop_target:.2f} {currency} or lower "
                f"(at least {drop_pct:g}% below `quote.current_price`) at some point before departure?"
            ),
            criteria={
                "true": f"A fare of {drop_target:.2f} {currency} or less is offered before departure.",
                "false": f"The fare never gets as low as {drop_target:.2f} {currency} before departure.",
            },
        ),
    }


def advise(
    quote: Quote,
    client: SystemOneClient | None = None,
    *,
    model: str | None = None,
    drop_pct: float = DEFAULT_DROP_PCT,
) -> Advice:
    """Return Jev's probabilities that now is the best price, and that a meaningful drop is coming.

    `client` defaults to a `TypeSafeClient`, which reads `TYPESAFE_API_KEY` from the environment.
    """
    drop_target = round(quote.current_price * (1 - drop_pct / 100), 2)
    questions = build_questions(quote, drop_target, drop_pct)
    state = build_state(quote)

    if client is None:
        with TypeSafeClient() as owned:
            result = owned.system_one(state, questions, model=model)
    else:
        result = client.system_one(state, questions, model=model)

    p_best = result.nouls["best_now"].noul
    # A drop of drop_pct% implies the current fare wasn't the best, so it can't be more likely than that.
    p_drop = min(result.nouls["meaningful_drop"].noul, 1.0 - p_best)
    return Advice(
        p_best_now=p_best,
        p_meaningful_drop=p_drop,
        drop_target=drop_target,
        drop_pct=drop_pct,
        recommendation="wait" if p_drop >= WAIT_THRESHOLD else "book now",
        model=result.model,
    )
