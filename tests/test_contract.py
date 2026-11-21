"""The parcel contract's checks, run over every normalised sample."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from custom_components.omniva.const import ParcelStatus
from custom_components.omniva.parcels import (
    normalize_parcel,
    planned_for_status,
    planned_window,
)

from .payloads import (
    delivered_sample,
    envelope,
    event,
    in_progress_sample,
    pickup_sample,
    place,
)

CANONICAL_KEYS = [
    "carrier",
    "barcode",
    "sender",
    "receiver",
    "status",
    "raw_status",
    "delivered",
    "delivered_at",
    "planned_from",
    "planned_to",
    "pickup",
    "pickup_point",
    "url",
    "weight",
    "dimensions",
    "history",
    "raw",
]

ZONE = timezone(timedelta(hours=2))


def _collected() -> dict:
    return envelope(
        events=[
            event("TRT_SHIPMENT_DELIVERED", "2026-04-29T16:00:00Z", None, place()),
            event("TRT_SHIPMENT_STORED_IN_PM", "2026-04-29T09:00:00Z", None, place()),
        ],
        state="DELIVERED",
        channel="COURIER",
    )


def _returning() -> dict:
    return envelope(
        events=[
            event("TRT_SHIPMENT_RETURN", "2026-04-29T09:00:00Z"),
            event("TRT_SHIPMENT_REGISTERED", "2026-04-28T09:00:00Z"),
        ],
        channel="PARCEL_MACHINE",
        destination=place(),
    )


SAMPLES = {
    "delivered": delivered_sample,
    "active": in_progress_sample,
    "at_pickup_point": pickup_sample,
    "collected": _collected,
    "returning": _returning,
    "bare": lambda: {"shipmentBarcode": "EXAMPLE000001"},
}


@pytest.fixture(params=SAMPLES)
def parcel(request) -> dict:
    return normalize_parcel(SAMPLES[request.param]())


def test_keys_and_order(parcel):
    assert list(parcel) == CANONICAL_KEYS


def test_delivered_follows_status(parcel):
    assert parcel["delivered"] is (parcel["status"] is ParcelStatus.DELIVERED)


def test_delivered_at_only_when_delivered(parcel):
    if not parcel["delivered"]:
        assert parcel["delivered_at"] is None


def test_planned_is_empty(parcel):
    assert parcel["planned_from"] is None
    assert parcel["planned_to"] is None


def test_pickup_is_a_bool_and_the_point_needs_it(parcel):
    assert isinstance(parcel["pickup"], bool)
    if not parcel["pickup"]:
        assert parcel["pickup_point"] is None


def test_a_collected_pickup_parcel_stays_pickup():
    """Collected from a machine the scans name, with no chosen site on the reply."""
    parcel = normalize_parcel(_collected())
    assert parcel["status"] is ParcelStatus.DELIVERED
    assert parcel["delivered"] is True
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] == "Example parcel_machine"
    assert parcel["delivered_at"] is not None


def test_a_returning_pickup_parcel_stays_pickup():
    parcel = normalize_parcel(_returning())
    assert parcel["status"] is ParcelStatus.RETURNING
    assert parcel["delivered"] is False
    assert parcel["pickup"] is True


def test_a_delivered_courier_parcel_is_not_pickup():
    parcel = normalize_parcel(
        envelope(
            events=[event("TRT_SHIPMENT_DELIVERED", "2026-04-29T16:00:00Z")],
            state="DELIVERED",
        )
    )
    assert parcel["delivered"] is True
    assert parcel["pickup"] is False
    assert parcel["pickup_point"] is None


def test_a_moment_ends_at_the_end_of_that_day():
    start, end = planned_window("2099-04-29T13:00:00+02:00", None, zone=ZONE)
    assert start == "2099-04-29T13:00:00+02:00"
    last = datetime.fromisoformat(end)
    assert (last.hour, last.minute, last.second, last.microsecond) == (23, 59, 59, 0)
    assert last.date() == date(2099, 4, 29)


def test_a_date_covers_the_whole_day():
    start, end = planned_window("2099-04-29", None, zone=ZONE)
    first = datetime.fromisoformat(start)
    last = datetime.fromisoformat(end)
    assert (first.hour, first.minute, first.second) == (0, 0, 0)
    assert (last.hour, last.minute, last.second) == (23, 59, 59)
    assert first.date() == last.date() == date(2099, 4, 29)


def test_two_dates_run_from_the_first_start_to_the_last_end():
    start, end = planned_window("2099-04-29", "2099-04-30", zone=UTC)
    assert start == "2099-04-29T00:00:00+00:00"
    assert end == "2099-04-30T23:59:59+00:00"


def test_the_window_is_empty_once_the_parcel_is_done_or_waiting():
    window = ("2099-04-29T13:00:00+02:00", "2099-04-29T23:59:59+02:00")
    for status in (
        ParcelStatus.DELIVERED,
        ParcelStatus.AT_PICKUP_POINT,
        ParcelStatus.RETURNING,
    ):
        assert planned_for_status(status, *window) == (None, None)
    assert planned_for_status(ParcelStatus.IN_TRANSIT, *window) == window
