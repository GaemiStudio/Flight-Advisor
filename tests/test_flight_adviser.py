from datetime import date

import pytest

from flight_adviser import CABINS, ProviderError, Trip, load_json


def test_trip_round_trip_flag():
    trip = Trip(
        origin="SFO",
        destination="JFK",
        depart=date(2026, 2, 14),
        return_date=date(2026, 2, 21),
    )

    assert trip.round_trip is True
    assert trip.cabin == "economy"


def test_cabins_are_defined():
    assert CABINS == ("economy", "premium_economy", "business", "first")


def test_load_json_reads_fixture():
    quote = load_json("samples/sample_quote.json")

    assert quote.trip.origin == "SFO"
    assert quote.trip.destination == "LAX"
    assert quote.current_price == 214.0
    assert quote.source == "sample fixture"


def test_fetch_serpapi_requires_api_key():
    trip = Trip(
        origin="SFO",
        destination="LAX",
        depart=date(2026, 3, 1),
    )

    with pytest.raises(ProviderError, match="SERPAPI_API_KEY"):
        from flight_adviser.providers import fetch_serpapi

        fetch_serpapi(trip)


class _FakeClient:
    def __init__(self, best_now: float, meaningful_drop: float):
        self.answers = {"best_now": best_now, "meaningful_drop": meaningful_drop}
        self.calls = []

    def system_one(self, state, questions, **kwargs):
        from typesafe_sdk import SystemOneResponse

        self.calls.append((state, questions, kwargs))
        return SystemOneResponse.model_validate(
            {
                "model": "jev-test",
                "usage": {"input_tokens": 1},
                "answers": {k: {"type": "noul", "noul": v} for k, v in self.answers.items()},
            }
        )


def test_advise_sends_quote_facts_and_reads_probabilities():
    from flight_adviser import advise

    quote = load_json("samples/sample_quote.json")
    client = _FakeClient(best_now=0.7, meaningful_drop=0.1)

    advice = advise(quote, client)

    state, questions, _ = client.calls[0]
    assert set(questions) == {"best_now", "meaningful_drop"}
    assert state["quote"]["days_until_departure"] == 9
    assert state["quote"]["position_in_typical_range_pct"] == 42.5
    assert state["price_history_summary"]["lowest_seen"] == 214.0
    assert advice.p_best_now == 0.7
    assert advice.p_future_better == pytest.approx(0.3)
    assert advice.drop_target == 203.3
    assert advice.recommendation == "book now"
    assert advice.model == "jev-test"


def test_advise_recommends_waiting_when_drop_is_likely():
    from flight_adviser import advise

    advice = advise(load_json("samples/sample_quote.json"), _FakeClient(best_now=0.2, meaningful_drop=0.65))

    assert advice.recommendation == "wait"


def test_meaningful_drop_is_capped_by_chance_of_any_drop():
    from flight_adviser import advise

    advice = advise(load_json("samples/sample_quote.json"), _FakeClient(best_now=0.6, meaningful_drop=0.55))

    assert advice.p_meaningful_drop == pytest.approx(0.4)
    assert advice.recommendation == "book now"
