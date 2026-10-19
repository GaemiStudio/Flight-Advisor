"""Command-line entry point for the flight adviser."""

from __future__ import annotations

import argparse
from datetime import date

from typesafe_sdk import TypeSafeError

from .advice import DEFAULT_DROP_PCT, advise
from .models import Trip
from .providers import ProviderError, fetch_serpapi, load_json


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check flight fares for a trip.")
    parser.add_argument("origin", nargs="?", help="IATA code for the departure airport")
    parser.add_argument("destination", nargs="?", help="IATA code for the arrival airport")
    parser.add_argument("depart", nargs="?", help="Departure date in YYYY-MM-DD format")
    parser.add_argument("--return-date", help="Return date in YYYY-MM-DD format")
    parser.add_argument("--cabin", choices=("economy", "premium_economy", "business", "first"), default="economy")
    parser.add_argument("--adults", type=int, default=1)
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--api-key", help="SerpApi key; if omitted, uses SERPAPI_API_KEY environment variable")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--sample", help="Load a sample quote from a JSON file instead of querying the live provider")
    parser.add_argument("--no-advice", action="store_true", help="Skip the Jev buy-or-wait assessment")
    parser.add_argument("--model", help="TypeSafe model ID (default: TYPESAFE_DEFAULT_MODEL or jev-latest)")
    parser.add_argument(
        "--drop-pct",
        type=float,
        default=DEFAULT_DROP_PCT,
        help="Smallest future price drop, in percent, worth waiting for (default: %(default)s)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.sample:
        quote = load_json(args.sample)
    else:
        if not (args.origin and args.destination and args.depart):
            parser.error("origin, destination, and depart are required unless --sample is used")

        trip = Trip(
            origin=args.origin,
            destination=args.destination,
            depart=date.fromisoformat(args.depart),
            return_date=date.fromisoformat(args.return_date) if args.return_date else None,
            cabin=args.cabin,
            adults=args.adults,
            currency=args.currency,
        )
        try:
            quote = fetch_serpapi(trip, api_key=args.api_key, timeout=args.timeout)
        except ProviderError as exc:
            parser.exit(1, f"{exc}\n")

    print(f"{quote.trip.origin} -> {quote.trip.destination} ({quote.trip.depart.isoformat()})")
    print(f"Current price: {quote.current_price:.2f} {quote.trip.currency}")
    if quote.itinerary:
        print(f"Itinerary: {quote.itinerary}")
    if quote.typical_range:
        low, high = quote.typical_range
        print(f"Typical range: {low:.2f} - {high:.2f} {quote.trip.currency}")

    if args.no_advice:
        return 0
    try:
        advice = advise(quote, model=args.model, drop_pct=args.drop_pct)
    except TypeSafeError as exc:
        print(f"\nNo Jev advice: {exc}")
        return 0

    print(f"\nJev ({advice.model}):")
    print(f"  P(now is the best price):      {advice.p_best_now:.0%}")
    print(f"  P(a lower fare comes later):   {advice.p_future_better:.0%}")
    print(
        f"  P(drops {advice.drop_pct:g}%+ to {advice.drop_target:.2f} {quote.trip.currency}): "
        f"{advice.p_meaningful_drop:.0%}"
    )
    print(f"  Recommendation: {advice.recommendation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
