"""Plain data types shared across the adviser."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


CABINS = ("economy", "premium_economy", "business", "first")


@dataclass
class Trip:
    origin: str
    destination: str
    depart: date
    return_date: date | None = None
    cabin: str = "economy"
    adults: int = 1
    currency: str = "USD"
    notes: str = ""  # free-text traveler context, e.g. "going to a wedding, dates fixed"

    @property
    def round_trip(self) -> bool:
        return self.return_date is not None


@dataclass
class PricePoint:
    observed: date
    price: float


@dataclass
class Quote:
    """The current fare for a trip plus whatever price history the provider has."""

    trip: Trip
    as_of: date
    current_price: float
    history: list[PricePoint] = field(default_factory=list)
    typical_range: tuple[float, float] | None = None
    provider_level: str | None = None  # e.g. Google Flights' "low" / "typical" / "high"
    itinerary: str = ""  # human-readable description of the cheapest option
    source: str = ""
