"""Where fares come from: SerpApi's Google Flights engine, or a local JSON file."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .models import CABINS, PricePoint, Quote, Trip

SERPAPI_URL = "https://serpapi.com/search.json"


class ProviderError(RuntimeError):
    pass


def _parse_price_history(raw_history: Any) -> list[PricePoint]:
    history: list[PricePoint] = []
    for value in raw_history or []:
        if isinstance(value, dict):
            ts = value.get("date") or value.get("observed")
            price = value.get("price")
            if ts is None or price is None:
                continue
            history.append(PricePoint(date.fromisoformat(str(ts)), float(price)))
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            ts, price = value[0], value[1]
            if isinstance(ts, (int, float)):
                history.append(PricePoint(datetime.fromtimestamp(ts, tz=timezone.utc).date(), float(price)))
            else:
                history.append(PricePoint(date.fromisoformat(str(ts)), float(price)))
    return history


def fetch_serpapi(trip: Trip, api_key: str | None = None, timeout: float = 60.0) -> Quote:
    """Look up current fares and Google's price insights for `trip`."""
    api_key = api_key or os.getenv("SERPAPI_API_KEY")
    if not api_key:
        raise ProviderError("SERPAPI_API_KEY is not set (or use --sample for offline data).")

    params = {
        "engine": "google_flights",
        "departure_id": trip.origin,
        "arrival_id": trip.destination,
        "outbound_date": trip.depart.isoformat(),
        "type": "1" if trip.round_trip else "2",
        "travel_class": str(CABINS.index(trip.cabin) + 1),
        "adults": str(trip.adults),
        "currency": trip.currency,
        "hl": "en",
        "api_key": api_key,
    }
    if trip.return_date:
        params["return_date"] = trip.return_date.isoformat()

    try:
        resp = httpx.get(SERPAPI_URL, params=params, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise ProviderError(f"SerpApi request failed: {e}") from e

    data = resp.json()
    if "error" in data:
        raise ProviderError(f"SerpApi: {data['error']}")

    best_flights = data.get("best_flights") or []
    other_flights = data.get("other_flights") or []
    options = [
        option for option in best_flights + other_flights if isinstance(option, dict) and option.get("price") is not None
    ]
    insights = data.get("price_insights") or {}
    if not options and not insights.get("lowest_price"):
        raise ProviderError("No priced itineraries returned for this search.")

    cheapest = min(options, key=lambda option: option["price"]) if options else None
    current = cheapest["price"] if cheapest else insights.get("lowest_price")
    if current is None:
        raise ProviderError("No valid price was returned for this trip.")

    history = _parse_price_history(insights.get("price_history"))
    typical = insights.get("typical_price_range")

    return Quote(
        trip=trip,
        as_of=date.today(),
        current_price=float(current),
        history=history,
        typical_range=(float(typical[0]), float(typical[1])) if isinstance(typical, (list, tuple)) and len(typical) == 2 else None,
        provider_level=insights.get("price_level"),
        itinerary=_describe_option(cheapest) if cheapest else "",
        source="Google Flights via SerpApi",
    )


def _describe_option(option: dict) -> str:
    legs = option.get("flights") or []
    airlines = sorted({str(leg.get("airline") or "?") for leg in legs if isinstance(leg, dict)})
    stops = max(len(legs) - 1, 0)
    duration = option.get("total_duration") or 0
    hours = float(duration) / 60 if duration else 0.0
    stop_text = "nonstop" if stops == 0 else f"{stops} stop{'s' if stops > 1 else ''}"
    return f"{', '.join(airlines) or 'flight'}, {stop_text}, {hours:.1f}h outbound"


def load_json(path: str | Path) -> Quote:
    """Load a quote from a JSON file (see samples/ for the format)."""
    raw = json.loads(Path(path).read_text())
    t = raw["trip"]
    return_value = t.get("return") or t.get("return_date")
    trip = Trip(
        origin=t["origin"],
        destination=t["destination"],
        depart=date.fromisoformat(t["depart"]),
        return_date=date.fromisoformat(str(return_value)) if return_value else None,
        cabin=t.get("cabin", "economy"),
        adults=t.get("adults", 1),
        currency=t.get("currency", "USD"),
        notes=t.get("notes", ""),
    )
    typical = raw.get("typical_range")
    return Quote(
        trip=trip,
        as_of=date.fromisoformat(raw["as_of"]),
        current_price=float(raw["current_price"]),
        history=_parse_price_history(raw.get("history", [])),
        typical_range=(float(typical[0]), float(typical[1])) if isinstance(typical, (list, tuple)) and len(typical) == 2 else None,
        provider_level=raw.get("provider_level"),
        itinerary=raw.get("itinerary", ""),
        source=raw.get("source", f"file: {Path(path).name}"),
    )
