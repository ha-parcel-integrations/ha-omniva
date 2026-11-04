"""Tests for the pure parcel-mapping helpers."""

from datetime import UTC, datetime, timedelta

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.omniva.const import (
    CAPABILITIES,
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DOMAIN,
    KNOWN_CAPABILITIES,
    PENDING_CAPABILITIES,
    ParcelStatus,
)
from custom_components.omniva.parcels import (
    _STATUS_MAP,
    apply_delivered_filter,
    map_event_status,
    map_parcel_status,
    normalize_parcel,
    parse_iso,
    sort_parcels_by_ts,
    tracking_url,
)

from .payloads import (
    ACTIVE_CODE,
    DELIVERED_CODE,
    active_sample,
    delivered_sample,
    envelope,
    event,
    failed_then_redirected_sample,
    in_progress_sample,
    pickup_sample,
    place,
)

DAY1 = "2026-03-01T10:00:00Z"
DAY2 = "2026-03-02T10:00:00Z"
DAY3 = "2026-03-03T10:00:00Z"
DAY4 = "2026-03-04T10:00:00Z"

# ---------------------------------------------------------------------------
# status map
# ---------------------------------------------------------------------------


def test_status_map_targets_only_the_canonical_enum():
    assert set(_STATUS_MAP.values()) <= set(ParcelStatus)
    assert ParcelStatus.UNKNOWN not in _STATUS_MAP.values()


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("TRT_SHIPMENT_REGISTERED", ParcelStatus.REGISTERED),
        ("TRT_SHIPMENT_REGISTERED_IN_OMNIVA", ParcelStatus.REGISTERED),
        ("REGISTERED", ParcelStatus.REGISTERED),
        ("TRT_SHIPMENT_HANDOVER_TO_PM", ParcelStatus.IN_TRANSIT),
        ("TRT_SHIPMENT_PICKED_UP_BY_COURIER", ParcelStatus.IN_TRANSIT),
        ("TRT_SHIPMENT_ARRIVED_TO_PO", ParcelStatus.IN_TRANSIT),
        ("TRT_SHIPMENT_REDIRECTION", ParcelStatus.IN_TRANSIT),
        ("TRT_SHIPMENT_HELD_IN_CUSTOMS", ParcelStatus.IN_TRANSIT),
        ("CARGO_SHIPMENT_HANDOVER_FROM_LINEHAUL_EVENT", ParcelStatus.IN_TRANSIT),
        ("IN_PROGRESS", ParcelStatus.IN_TRANSIT),
        ("IN_POST_OFFICE", ParcelStatus.IN_TRANSIT),
        ("IN_CUSTOMS", ParcelStatus.IN_TRANSIT),
        ("TRT_SHIPMENT_COURIER_DELIVERY_STARTED", ParcelStatus.OUT_FOR_DELIVERY),
        ("CARGO_SHIPMENT_OUT_FOR_DELIVERY", ParcelStatus.OUT_FOR_DELIVERY),
        ("ON_COURIER_DELIVERY", ParcelStatus.OUT_FOR_DELIVERY),
        ("TRT_SHIPMENT_STORED_IN_PM", ParcelStatus.AT_PICKUP_POINT),
        ("TRT_SHIPMENT_ARRIVED_TO_FINAL_PO", ParcelStatus.AT_PICKUP_POINT),
        ("READY_FOR_PICKUP", ParcelStatus.AT_PICKUP_POINT),
        ("IN_PARCEL_MACHINE", ParcelStatus.AT_PICKUP_POINT),
        ("TRT_SHIPMENT_FAILED_DELIVERY_ATTEMPT", ParcelStatus.PROBLEM),
        ("CARGO_SHIPMENT_DELIVERY_FAILED", ParcelStatus.PROBLEM),
        ("TRT_SHIPMENT_MOVEMENT_STOPPED", ParcelStatus.PROBLEM),
        ("CARGO_SHIPMENT_DESTROYED", ParcelStatus.PROBLEM),
        ("WRITTEN_OFF", ParcelStatus.PROBLEM),
        ("TRT_SHIPMENT_RETURN", ParcelStatus.RETURNING),
        ("CARGO_SHIPMENT_POSTED_IN_RETURNING_COUNTRY", ParcelStatus.RETURNING),
        ("RETURNED", ParcelStatus.RETURNING),
        ("TRT_SHIPMENT_DELIVERED", ParcelStatus.DELIVERED),
        ("CARGO_SHIPMENT_DELIVERED", ParcelStatus.DELIVERED),
        ("TRT_SHIPMENT_EMI", ParcelStatus.DELIVERED),
        ("DELIVERED", ParcelStatus.DELIVERED),
    ],
)
def test_map_parcel_status_known(code, expected):
    assert map_parcel_status(code) == expected


def test_map_parcel_status_missing_is_silently_unknown(caplog):
    assert map_parcel_status(None) == ParcelStatus.UNKNOWN
    assert map_parcel_status("") == ParcelStatus.UNKNOWN
    assert caplog.text == ""


def test_map_event_status_missing_and_unmapped_are_none():
    """History keeps ``null`` rather than ``unknown`` so consumers can tell
    "no mapping" from "mapped to unknown"."""
    assert map_event_status(None) is None
    assert map_event_status("SOMETHING_NEW") is None
    assert map_event_status("TRT_SHIPMENT_DELIVERED") == ParcelStatus.DELIVERED


def test_unmapped_status_warns_only_once(caplog):
    assert map_parcel_status("ABDUCTED") == ParcelStatus.UNKNOWN
    assert map_parcel_status("ABDUCTED") == ParcelStatus.UNKNOWN
    assert caplog.text.count("ABDUCTED") == 1
    assert "issues/new?template=unrecognised_status.yml" in caplog.text
    assert all(record.levelname == "WARNING" for record in caplog.records)


# ---------------------------------------------------------------------------
# status resolution
# ---------------------------------------------------------------------------


def test_newest_scan_decides_whatever_the_list_order():
    parcel = normalize_parcel(in_progress_sample())
    assert parcel["status"] == ParcelStatus.IN_TRANSIT
    assert parcel["raw_status"].endswith("TRT_SHIPMENT_ARRIVED_TO_PO")

    shuffled = active_sample()
    shuffled["events"].reverse()
    assert normalize_parcel(shuffled)["status"] == ParcelStatus.OUT_FOR_DELIVERY


def test_scan_beats_a_generic_state():
    """The state stays "in progress" while the courier already has the parcel."""
    parcel = normalize_parcel(active_sample())
    assert parcel["raw"]["currentStateCode"] == "IN_PROGRESS"
    assert parcel["status"] == ParcelStatus.OUT_FOR_DELIVERY


def test_failed_attempt_then_next_round_is_out_for_delivery():
    events = [
        event("TRT_SHIPMENT_COURIER_DELIVERY_STARTED", DAY3),
        event("TRT_SHIPMENT_FAILED_DELIVERY_ATTEMPT", DAY2),
        event("TRT_SHIPMENT_COURIER_DELIVERY_STARTED", DAY1),
    ]
    assert normalize_parcel(envelope(events=events))["status"] == (
        ParcelStatus.OUT_FOR_DELIVERY
    )
    assert normalize_parcel(envelope(events=events[1:]))["status"] == (
        ParcelStatus.PROBLEM
    )


def test_full_journey_ends_delivered_at_the_machine():
    parcel = normalize_parcel(failed_then_redirected_sample(), include_history=True)
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] == "2026-03-17T16:29:18+00:00"
    assert parcel["pickup_point"] == "Example parcel_machine"
    assert [entry["status"] for entry in parcel["history"]] == [
        ParcelStatus.REGISTERED,
        ParcelStatus.IN_TRANSIT,
        ParcelStatus.OUT_FOR_DELIVERY,
        ParcelStatus.PROBLEM,
        ParcelStatus.IN_TRANSIT,
        ParcelStatus.AT_PICKUP_POINT,
        ParcelStatus.DELIVERED,
    ]


def test_notice_keeps_the_stage_of_the_scan_before_it(caplog):
    raw = envelope(
        events=[
            event(
                "TRT_SHIPMENT_ARRIVAL_PM_NOTIFICATION", DAY2, "We told the recipient"
            ),
            event("TRT_SHIPMENT_STORED_IN_PM", DAY1, "Ready", place()),
        ],
    )
    parcel = normalize_parcel(raw, include_history=True)
    assert parcel["status"] == ParcelStatus.AT_PICKUP_POINT
    assert parcel["raw_status"] == "We told the recipient"
    assert [entry["raw_status"] for entry in parcel["history"]] == ["Ready"]
    assert "NOTIFICATION" not in caplog.text


def test_only_notices_fall_to_the_state():
    raw = envelope(events=[event("TRT_SHIPMENT_MEASURED", DAY1)], state="IN_TRANSIT")
    assert normalize_parcel(raw)["status"] == ParcelStatus.IN_TRANSIT


@pytest.mark.parametrize(
    "code",
    [
        "CARGO_SHIPMENT_WAITING_FOR_PAYMENT",
        "CARGO_SHIPMENT_DELIVERED_TO_RETURNS_CENTER",
    ],
)
def test_unmapped_scan_falls_back_to_newest_mappable_scan(code, caplog):
    raw = envelope(
        events=[
            event(code, DAY3, "Unseen wording, Jane Doe +37200000000"),
            event("TRT_SHIPMENT_ARRIVED_TO_PO", DAY2),
            event("TRT_SHIPMENT_REGISTERED", DAY1),
        ],
        state="SOME_NEW_STATE_A",
    )
    parcel = normalize_parcel(raw, include_history=True)
    normalize_parcel(raw)

    assert parcel["status"] == ParcelStatus.IN_TRANSIT
    assert parcel["raw_status"] == "Unseen wording, Jane Doe +37200000000"
    assert parcel["history"][-1]["status"] is None
    assert caplog.text.count(f"status={code}") == 1
    assert "Jane Doe" not in caplog.text
    assert "+37200000000" not in caplog.text


SCAN_STATUSES = {
    ParcelStatus.REGISTERED: (
        "TRT_SHIPMENT_REGISTERED",
        "TRT_SHIPMENT_REGISTERED_IN_OMNIVA",
    ),
    ParcelStatus.IN_TRANSIT: (
        "TRT_SHIPMENT_HANDOVER_TO_PM",
        "TRT_SHIPMENT_HANDOVER_TO_PO",
        "TRT_SHIPMENT_PICKED_UP_BY_COURIER",
        "TRT_SHIPMENT_ARRIVED_TO_PO",
        "TRT_SHIPMENT_DEPARTED_FROM_PM",
        "TRT_SHIPMENT_REDIRECTION",
        "TRT_SHIPMENT_MOVEMENT_RESTORED",
        "TRT_SHIPMENT_RETURN_CANCELLED",
        "TRT_SHIPMENT_COURIER_DELIVERY_CANCELLED",
        "TRT_SHIPMENT_TAKEN_TO_CUSTOMS",
        "TRT_SHIPMENT_RELEASED_FROM_CUSTOMS",
        "TRT_SHIPMENT_ARRIVAL_CUSTOMS_NOTIFICATION",
        "TRT_SHIPMENT_CD_REMINDER_NOTIFICATION",
        "TRT_SHIPMENT_CD_ADD_PAYMENT_NOTIFICATION",
        "TRT_SHIPMENT_CD_ADD_PAYMENT_REMINDER_NOTIFICATION",
        "TRT_SHIPMENT_EDA",
        "TRT_SHIPMENT_EDB",
        "TRT_SHIPMENT_EDC",
        "TRT_SHIPMENT_EDD",
        "TRT_SHIPMENT_EDF",
        "TRT_SHIPMENT_EMA",
        "TRT_SHIPMENT_EMB",
        "TRT_SHIPMENT_EMC",
        "TRT_SHIPMENT_EMD",
        "TRT_SHIPMENT_EME",
        "TRT_SHIPMENT_EMF",
        "TRT_SHIPMENT_EMG",
        "TRT_SHIPMENT_EMJ",
        "CARGO_SHIPMENT_IN_TRANSIT_TO_DESTINATION_COUNTRY",
        "CARGO_SHIPMENT_ARRIVED_TO_DESTINATION_COUNTRY",
        "CARGO_SHIPMENT_ARRIVED_TO_LAST_DELIVERY_OFFICE",
        "CARGO_SHIPMENT_ARRIVED_TO_TRANSIT_HUB",
        "CARGO_SHIPMENT_DEPARTED_FROM_TRANSIT_HUB",
        "CARGO_SHIPMENT_PRESENTED_TO_CUSTOMS",
        "CARGO_SHIPMENT_HELD_IN_CUSTOMS",
        "CARGO_SHIPMENT_RELEASED_FROM_CUSTOMS",
        "CARGO_SHIPMENT_ARRIVED_TO_RETURNING_COUNTRY_HUB",
        "CARGO_SHIPMENT_DEPARTED_FROM_RETURNING_COUNTRY",
    ),
    ParcelStatus.OUT_FOR_DELIVERY: (
        "TRT_SHIPMENT_COURIER_DELIVERY_STARTED",
        "TRT_SHIPMENT_EDG",
    ),
    ParcelStatus.AT_PICKUP_POINT: (
        "TRT_SHIPMENT_STORED_IN_PM",
        "TRT_SHIPMENT_ARRIVED_TO_FINAL_PO",
        "TRT_SHIPMENT_EDH",
        "CARGO_SHIPMENT_ARRIVED_TO_LAST_PICKUP_POINT",
    ),
    ParcelStatus.PROBLEM: (
        "TRT_SHIPMENT_FAILED_DELIVERY_ATTEMPT",
        "TRT_SHIPMENT_CANCELLED",
        "TRT_SHIPMENT_MOVEMENT_STOPPED",
        "TRT_SHIPMENT_MISSING_IN_PM",
        "TRT_SHIPMENT_EMH",
        "TRT_SHIPMENT_EDX",
        "TRT_SHIPMENT_EXX",
        "CARGO_SHIPMENT_DELIVERY_FAILED",
        "CARGO_SHIPMENT_DESTROYED",
    ),
    ParcelStatus.RETURNING: (
        "TRT_SHIPMENT_RETURN",
        "TRT_SHIPMENT_RETURNED_BY_CUSTOMER",
        "CARGO_SHIPMENT_POSTED_IN_RETURNING_COUNTRY",
        "CARGO_SHIPMENT_RETURNED",
    ),
    ParcelStatus.DELIVERED: (
        "TRT_SHIPMENT_DELIVERED",
        "TRT_SHIPMENT_EMI",
        "CARGO_SHIPMENT_DELIVERED",
    ),
}
STATE_STATUSES = {
    ParcelStatus.REGISTERED: ("REGISTERED",),
    ParcelStatus.IN_TRANSIT: ("IN_PROGRESS",),
    ParcelStatus.OUT_FOR_DELIVERY: ("ON_COURIER_DELIVERY",),
    ParcelStatus.AT_PICKUP_POINT: ("READY_FOR_PICKUP",),
    ParcelStatus.PROBLEM: ("CANCELLED",),
    ParcelStatus.RETURNING: ("RETURNED",),
    ParcelStatus.DELIVERED: ("DELIVERED",),
}
NOTICE_CODES = (
    "TRT_COURIER_CALLED_TO_RECEIVER",
    "TRT_COURIER_PRE_DELIVERY_RECIPIENT_NOTIFICATION",
    "TRT_SHIPMENT_ARRIVAL_PM_NOTIFICATION",
    "TRT_SHIPMENT_ARRIVAL_PO_NOTIFICATION",
    "TRT_SHIPMENT_REMINDER_PM_NOTIFICATION",
    "TRT_SHIPMENT_REMINDER_PO_NOTIFICATION",
    "TRT_SHIPMENT_RECIPIENT_NOTIFICATION_EVENT",
    "TRT_SHIPMENT_RECIPIENT_CONTACT_UPDATED",
    "TRT_SHIPMENT_DECLARATION_CANCELLED",
    "TRT_SHIPMENT_DOC_RETURN_SENDER",
    "TRT_SHIPMENT_DELIVERY_PARTNER_BARCODE_ASSIGNED",
    "CARGO_SHIPMENT_DELIVERY_PARTNER_BARCODE_ASSIGNED",
)
RETURN_START_CODES = (
    "TRT_SHIPMENT_RETURN",
    "TRT_SHIPMENT_RETURNED_BY_CUSTOMER",
    "CARGO_SHIPMENT_POSTED_IN_RETURNING_COUNTRY",
    "CARGO_SHIPMENT_RETURNED",
)


@pytest.mark.parametrize(
    ("code", "status"),
    [(code, status) for status, codes in SCAN_STATUSES.items() for code in codes],
)
def test_every_known_scan_maps_without_a_warning(code, status, caplog):
    raw = envelope(events=[event(code, DAY2), event("TRT_SHIPMENT_REGISTERED", DAY1)])
    assert normalize_parcel(raw)["status"] == status
    assert "Unrecognised" not in caplog.text


@pytest.mark.parametrize(
    ("state", "status"),
    [(state, status) for status, states in STATE_STATUSES.items() for state in states],
)
def test_every_known_state_maps_without_a_warning(state, status, caplog):
    assert normalize_parcel(envelope(state=state))["status"] == status
    assert "Unrecognised" not in caplog.text


@pytest.mark.parametrize("code", NOTICE_CODES)
def test_every_notice_keeps_the_stage_without_a_warning(code, caplog):
    raw = envelope(
        events=[
            event(code, DAY2, "A message"),
            event("TRT_SHIPMENT_ARRIVED_TO_PO", DAY1, "At the office"),
        ],
    )
    parcel = normalize_parcel(raw, include_history=True)
    assert parcel["status"] == ParcelStatus.IN_TRANSIT
    assert parcel["raw_status"] == "A message"
    assert [entry["raw_status"] for entry in parcel["history"]] == ["At the office"]
    assert "Unrecognised" not in caplog.text


@pytest.mark.parametrize("code", RETURN_START_CODES)
def test_every_return_start_makes_a_later_delivery_returning(code):
    raw = envelope(
        events=[
            event("CARGO_SHIPMENT_DELIVERED", DAY3),
            event(code, DAY2),
            event("TRT_SHIPMENT_REGISTERED", DAY1),
        ],
    )
    parcel = normalize_parcel(raw)
    assert parcel["status"] == ParcelStatus.RETURNING
    assert parcel["delivered"] is False


def test_returned_state_makes_a_delivered_scan_returning():
    raw = envelope(events=[event("TRT_SHIPMENT_DELIVERED", DAY1)], state="RETURNED")
    parcel = normalize_parcel(raw)
    assert parcel["status"] == ParcelStatus.RETURNING
    assert parcel["delivered"] is False


@pytest.mark.parametrize(
    ("state", "status"),
    [
        ("DELIVERED", ParcelStatus.DELIVERED),
        ("CANCELLED", ParcelStatus.PROBLEM),
        ("RETURNED", ParcelStatus.RETURNING),
    ],
)
def test_definite_state_beats_an_older_scan_under_an_unreadable_one(
    state, status, caplog
):
    raw = envelope(
        events=[
            event("BRAND_NEW_SCAN", DAY2),
            event("TRT_SHIPMENT_STORED_IN_PM", DAY1, location=place()),
        ],
        state=state,
    )
    assert normalize_parcel(raw)["status"] == status
    assert "status=BRAND_NEW_SCAN" in caplog.text


def test_generic_state_does_not_beat_an_older_scan_under_an_unreadable_one():
    raw = envelope(
        events=[
            event("BRAND_NEW_SCAN", DAY2),
            event("TRT_SHIPMENT_STORED_IN_PM", DAY1, location=place()),
        ],
        state="IN_PROGRESS",
    )
    assert normalize_parcel(raw)["status"] == ParcelStatus.AT_PICKUP_POINT


@pytest.mark.parametrize(
    "newest",
    ["TRT_SHIPMENT_ARRIVAL_PM_NOTIFICATION", "TRT_SHIPMENT_STORED_IN_PM"],
)
def test_definite_state_does_not_beat_a_scan_we_can_read(newest):
    raw = envelope(
        events=[
            event(newest, DAY2),
            event("TRT_SHIPMENT_STORED_IN_PM", DAY1, location=place()),
        ],
        state="DELIVERED",
    )
    assert normalize_parcel(raw)["status"] == ParcelStatus.AT_PICKUP_POINT


@pytest.mark.parametrize(
    "mangle",
    [
        lambda raw: raw.update(currentStateCode={"odd": 1}),
        lambda raw: raw.update(currentDeliveryChannel=["odd"]),
        lambda raw: raw["events"][0].update(eventCode=["odd"]),
        lambda raw: raw["events"][0]["location"].update(servicePointTypeCode=["odd"]),
        lambda raw: raw["events"][0]["location"].update(countryCode=["odd"]),
        lambda raw: raw["events"][0].update(eventParameters=[{"name": ["odd"]}]),
        lambda raw: raw.update(deliveryLocation={"servicePointTypeCode": ["odd"]}),
        lambda raw: raw.update(deliveryLocation={"countryCode": ["odd"]}),
    ],
)
def test_a_code_that_is_not_text_never_fails_the_poll(mangle, caplog):
    raw = envelope(events=[event("TRT_SHIPMENT_DELIVERED", DAY1, location=place())])
    mangle(raw)
    assert (
        normalize_parcel(raw, include_history=True)["barcode"] == raw["shipmentBarcode"]
    )
    assert "odd" not in caplog.text


def test_unmapped_scan_with_nothing_else_is_unknown_and_warns(caplog):
    raw = envelope(events=[event("BRAND_NEW_SCAN", DAY1)], state="BRAND_NEW_STATE")
    parcel = normalize_parcel(raw)
    assert parcel["status"] == ParcelStatus.UNKNOWN
    assert "status=BRAND_NEW_SCAN" in caplog.text
    assert "status=BRAND_NEW_STATE" in caplog.text


def test_unmapped_state_warns_even_when_a_scan_decides(caplog):
    raw = envelope(
        events=[event("TRT_SHIPMENT_SORTED", DAY1)], state="NEVER_SEEN_STATE"
    )
    assert normalize_parcel(raw)["status"] == ParcelStatus.IN_TRANSIT
    assert "status=NEVER_SEEN_STATE" in caplog.text


@pytest.mark.parametrize(
    ("state", "expected", "delivered"),
    [
        ("DELIVERED", ParcelStatus.DELIVERED, True),
        ("IN_PARCEL_MACHINE", ParcelStatus.AT_PICKUP_POINT, False),
        ("ON_COURIER_DELIVERY", ParcelStatus.OUT_FOR_DELIVERY, False),
        ("LOST", ParcelStatus.PROBLEM, False),
    ],
)
def test_empty_events_read_from_the_state(state, expected, delivered):
    parcel = normalize_parcel(envelope(state=state), include_history=True)
    assert parcel["status"] == expected
    assert parcel["delivered"] is delivered
    assert parcel["delivered_at"] is None
    assert parcel["raw_status"] == state
    assert parcel["history"] == []


# ---------------------------------------------------------------------------
# returns
# ---------------------------------------------------------------------------


def test_delivered_after_a_return_started_is_returning():
    raw = envelope(
        events=[
            event("TRT_SHIPMENT_DELIVERED", DAY3, "Shipment delivered", place()),
            event("TRT_SHIPMENT_RETURN", DAY2),
            event("TRT_SHIPMENT_REGISTERED", DAY1),
        ],
        state="DELIVERED",
        channel="PARCEL_MACHINE",
        destination=place(),
    )
    parcel = normalize_parcel(raw, include_history=True)
    assert parcel["status"] == ParcelStatus.RETURNING
    assert parcel["delivered"] is False
    assert parcel["delivered_at"] is None
    # A return's site is the sender's, not a pickup point the recipient can use.
    assert parcel["pickup"] is False
    assert parcel["pickup_point"] is None
    assert parcel["history"][-1]["status"] == ParcelStatus.RETURNING


def test_delivered_with_only_the_return_flag_is_returning():
    raw = delivered_sample()
    raw["returningShipment"] = True
    parcel = normalize_parcel(raw)
    assert parcel["status"] == ParcelStatus.RETURNING
    assert parcel["delivered"] is False


def test_delivered_state_alone_with_the_return_flag_is_returning():
    parcel = normalize_parcel(envelope(state="DELIVERED", returning=True))
    assert parcel["status"] == ParcelStatus.RETURNING


def test_delivered_before_a_later_return_scan_is_returning():
    raw = envelope(
        events=[
            event("TRT_SHIPMENT_RETURN", DAY2),
            event("TRT_SHIPMENT_DELIVERED", DAY1),
        ],
    )
    assert normalize_parcel(raw)["status"] == ParcelStatus.RETURNING


def test_scans_on_the_way_back_stay_returning():
    raw = envelope(
        events=[
            event("TRT_SHIPMENT_ARRIVED_TO_PO", DAY2),
            event("TRT_SHIPMENT_RETURN", DAY1),
        ],
    )
    assert normalize_parcel(raw)["status"] == ParcelStatus.RETURNING


def test_problem_on_the_way_back_still_shows():
    raw = envelope(
        events=[
            event("TRT_SHIPMENT_MISSING_IN_PM", DAY2),
            event("TRT_SHIPMENT_RETURN", DAY1),
        ],
        returning=True,
    )
    parcel = normalize_parcel(raw)
    assert parcel["status"] == ParcelStatus.PROBLEM

    raw.update(currentDeliveryChannel="PARCEL_MACHINE", deliveryLocation=place())
    assert normalize_parcel(raw)["pickup"] is False


def test_cancelled_return_delivers_to_the_recipient():
    raw = envelope(
        events=[
            event("TRT_SHIPMENT_DELIVERED", DAY4),
            event("TRT_SHIPMENT_RETURN_CANCELLED", DAY3),
            event("TRT_SHIPMENT_RETURN", DAY2),
            event("TRT_SHIPMENT_REGISTERED", DAY1),
        ],
    )
    parcel = normalize_parcel(raw)
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["delivered"] is True


# ---------------------------------------------------------------------------
# timestamps and history
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-03-01T10:00:00Z", "2026-03-01T10:00:00+00:00"),
        ("2026-03-01T10:00:00.1Z", "2026-03-01T10:00:00.100000+00:00"),
        ("2026-03-01T10:00:00.12Z", "2026-03-01T10:00:00.120000+00:00"),
        ("2026-03-01T10:00:00.123Z", "2026-03-01T10:00:00.123000+00:00"),
        ("2026-03-01T10:00:00.1234Z", "2026-03-01T10:00:00.123400+00:00"),
        ("2026-03-01T10:00:00.12345Z", "2026-03-01T10:00:00.123450+00:00"),
        ("2026-03-01T10:00:00.123456Z", "2026-03-01T10:00:00.123456+00:00"),
        ("2026-03-01T10:00:00.1234567Z", "2026-03-01T10:00:00.123456+00:00"),
        ("2026-03-01T10:00:00.12345678Z", "2026-03-01T10:00:00.123456+00:00"),
        ("2026-03-01T10:00:00.123456789Z", "2026-03-01T10:00:00.123456+00:00"),
    ],
)
def test_clock_with_any_fraction_length(value, expected):
    raw = envelope(events=[event("TRT_SHIPMENT_DELIVERED", value)])
    parcel = normalize_parcel(raw, include_history=True)
    assert parcel["delivered_at"] == expected
    assert parcel["history"][0]["timestamp"] == expected


def test_parse_iso_handles_z_naive_and_garbage():
    assert parse_iso("2026-04-29T13:12:42Z").tzinfo is not None
    # A naive value is assumed UTC so mixed lists still sort.
    assert parse_iso("2026-04-29T13:12:42").tzinfo == UTC
    assert parse_iso("not-a-date") is None
    assert parse_iso(None) is None


def test_history_is_oldest_first_whatever_the_list_order():
    history = normalize_parcel(in_progress_sample(), include_history=True)["history"]
    stamps = [entry["timestamp"] for entry in history]
    assert stamps == sorted(stamps)
    assert history[0]["status"] == ParcelStatus.REGISTERED
    assert set(history[0]) == {"timestamp", "status", "raw_status"}


def test_same_second_pair_sorts_on_the_fraction():
    raw = envelope(
        events=[
            event("TRT_SHIPMENT_ARRIVED_TO_PO", "2026-03-01T10:00:00.2Z"),
            event("TRT_SHIPMENT_PICKED_UP_BY_COURIER", "2026-03-01T10:00:00.900Z", "b"),
            event("TRT_SHIPMENT_REGISTERED", "2026-03-01T10:00:00.1Z", "a"),
        ],
    )
    history = normalize_parcel(raw, include_history=True)["history"]
    assert history[0]["raw_status"] == "a"
    assert history[-1]["raw_status"] == "b"


def test_history_is_capped_to_the_newest_twenty():
    events = [
        event("TRT_SHIPMENT_ARRIVED_TO_PO", f"2026-03-{day:02d}T10:00:00Z", str(day))
        for day in range(1, 26)
    ]
    history = normalize_parcel(envelope(events=events), include_history=True)["history"]
    assert len(history) == 20
    assert history[0]["raw_status"] == "6"
    assert history[-1]["raw_status"] == "25"


def test_history_carries_no_parameters_or_locations():
    raw = envelope(
        events=[
            event(
                "TRT_SHIPMENT_FAILED_DELIVERY_ATTEMPT",
                DAY1,
                location=place(),
                parameters=[
                    {"name": "TASK_EVENT_REASON_CODE_ID", "value": "+37200000000"}
                ],
            )
        ],
    )
    history = normalize_parcel(raw, include_history=True)["history"]
    assert "+37200000000" not in str(history)
    assert "Example" not in str(history)


def test_scan_without_wording_falls_back_to_its_code():
    raw = envelope(events=[event("TRT_SHIPMENT_SORTED", DAY1, "")])
    assert normalize_parcel(raw)["raw_status"] == "TRT_SHIPMENT_SORTED"


def test_malformed_scans_are_skipped(caplog):
    raw = envelope(
        events=[
            "not-a-dict",
            event("TRT_SHIPMENT_DELIVERED", "not-a-date"),
            {"eventCode": "TRT_SHIPMENT_DELIVERED"},
            event("TRT_SHIPMENT_SORTED", DAY1),
        ],
    )
    parcel = normalize_parcel(raw, include_history=True)
    assert parcel["status"] == ParcelStatus.IN_TRANSIT
    assert len(parcel["history"]) == 1
    assert caplog.text.count("event_date=unparseable") == 1
    assert "not-a-date" not in caplog.text


def test_events_of_the_wrong_type_read_from_the_state():
    raw = envelope(state="IN_TRANSIT")
    raw["events"] = "nonsense"
    assert normalize_parcel(raw)["status"] == ParcelStatus.IN_TRANSIT


# ---------------------------------------------------------------------------
# unseen shapes
# ---------------------------------------------------------------------------


def test_unseen_shapes_warn_once_with_the_code_and_never_a_value(caplog):
    raw = envelope(
        events=[
            event(
                "TRT_SHIPMENT_SORTED",
                DAY1,
                location={**place(), "servicePointTypeCode": "NEW_SITE_TYPE"},
                parameters=[
                    {"name": "NEW_PARAMETER", "value": "+37200000000"},
                    "not-a-dict",
                ],
            )
        ],
        channel="NEW_CHANNEL",
    )
    normalize_parcel(raw)
    normalize_parcel(raw)

    assert caplog.text.count("service_point_type=NEW_SITE_TYPE") == 1
    assert caplog.text.count("event_parameter=NEW_PARAMETER") == 1
    assert caplog.text.count("delivery_channel=NEW_CHANNEL") == 1
    assert "+37200000000" not in caplog.text
    assert "Example" not in caplog.text


def test_seen_shapes_stay_silent(caplog):
    normalize_parcel(failed_then_redirected_sample())
    normalize_parcel(in_progress_sample())
    assert caplog.text == ""


# ---------------------------------------------------------------------------
# pickup point
# ---------------------------------------------------------------------------


def test_waiting_in_a_machine():
    parcel = normalize_parcel(pickup_sample())
    assert parcel["status"] == ParcelStatus.AT_PICKUP_POINT
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] == "Example parcel_machine"


def test_pickup_point_from_the_scan_without_a_chosen_site():
    raw = envelope(
        events=[
            event(
                "TRT_SHIPMENT_ARRIVED_TO_FINAL_PO", DAY1, location=place("POST_OFFICE")
            )
        ],
    )
    parcel = normalize_parcel(raw)
    assert parcel["pickup_point"] == "Example post_office"


def test_collected_after_a_scan_without_a_site_keeps_the_machine():
    raw = envelope(
        events=[
            event("TRT_SHIPMENT_DELIVERED", DAY3),
            event("TRT_SHIPMENT_MEASURED", DAY2, location=place("WORKSTATION")),
            event("TRT_SHIPMENT_STORED_IN_PM", DAY1, location=place()),
        ],
    )
    assert normalize_parcel(raw)["pickup_point"] == "Example parcel_machine"


def test_sender_drop_off_machine_is_not_the_pickup_point():
    """The machine the sender used must not show on a parcel the courier delivered."""
    raw = envelope(
        events=[
            event("TRT_SHIPMENT_DELIVERED", DAY3, location=place("CLIENT")),
            event("TRT_SHIPMENT_COURIER_DELIVERY_STARTED", DAY2),
            event("TRT_SHIPMENT_HANDOVER_TO_PM", DAY1, location=place()),
        ],
    )
    parcel = normalize_parcel(raw)
    assert parcel["delivered"] is True
    assert parcel["pickup_point"] is None
    assert parcel["pickup"] is False


def test_a_home_address_is_never_the_pickup_point():
    raw = envelope(
        events=[event("TRT_SHIPMENT_DELIVERED", DAY1, location=place("CLIENT"))],
        destination=place("CLIENT"),
    )
    assert normalize_parcel(raw)["pickup_point"] is None


def test_no_pickup_point_while_on_the_way_but_pickup_is_known():
    """The en-route sensor reads ``pickup`` before the parcel arrives."""
    raw = in_progress_sample()
    raw["currentDeliveryChannel"] = "PARCEL_MACHINE"
    raw["deliveryLocation"] = place()
    parcel = normalize_parcel(raw)
    assert parcel["status"] == ParcelStatus.IN_TRANSIT
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] is None


def test_chosen_post_office_counts_as_pickup_without_the_machine_channel():
    raw = in_progress_sample()
    raw["currentDeliveryChannel"] = None
    raw["deliveryLocation"] = place("POST_OFFICE")
    assert normalize_parcel(raw)["pickup"] is True


def test_courier_parcel_is_not_pickup():
    assert normalize_parcel(in_progress_sample())["pickup"] is False


# ---------------------------------------------------------------------------
# normalize_parcel — the canonical contract
# ---------------------------------------------------------------------------

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


def test_normalize_publishes_exactly_the_canonical_keys():
    """The aggregator and cross-carrier dashboards depend on this key set."""
    assert list(normalize_parcel(delivered_sample())) == CANONICAL_KEYS


def test_capabilities_are_known_values():
    """A typo here would silently misreport this carrier on the docs site."""
    assert CAPABILITIES <= KNOWN_CAPABILITIES
    assert PENDING_CAPABILITIES <= KNOWN_CAPABILITIES


def test_a_capability_is_never_both_populated_and_pending():
    """The docs site would have to pick one; "awaiting data" must not hide a confirmed field."""
    assert not CAPABILITIES & PENDING_CAPABILITIES


def test_capabilities_match_what_normalize_parcel_actually_returns():
    """Every declared CAPABILITIES entry comes true, every other field stays ``None``."""
    delivered = normalize_parcel(delivered_sample(), include_history=True)
    active = normalize_parcel(active_sample(), include_history=True)
    pickup = normalize_parcel(pickup_sample(), include_history=True)

    assert {"pickup_point", "url", "history"} == CAPABILITIES
    assert pickup["pickup_point"] is not None
    assert delivered["url"] is not None
    assert delivered["history"] is not None
    for parcel in (delivered, active, pickup):
        for field in ("planned_from", "planned_to", "weight", "dimensions"):
            assert parcel[field] is None


def test_normalize_trimmed_delivered_item():
    parcel = normalize_parcel(delivered_sample())
    assert parcel["carrier"] == "Omniva"
    assert parcel["barcode"] == DELIVERED_CODE
    assert parcel["sender"] is None
    assert parcel["receiver"] is None
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["raw_status"] == "Shipment delivered"
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] == "2026-03-05T12:50:22.097006+00:00"
    assert parcel["pickup_point"] == "Example parcel_machine"
    assert parcel["history"] is None  # opt-in, default off


def test_normalize_pending_placeholder():
    """A tracked-but-not-yet-known code still yields a full parcel dict."""
    parcel = normalize_parcel({"shipmentBarcode": ACTIVE_CODE})
    assert parcel["barcode"] == ACTIVE_CODE
    assert parcel["status"] == ParcelStatus.UNKNOWN
    assert parcel["delivered"] is False
    assert parcel["raw_status"] is None
    assert parcel["pickup"] is False
    assert parcel["url"] == f"https://minu.omniva.ee/track/{ACTIVE_CODE}"


def test_normalize_keeps_the_full_reply_untrimmed():
    raw = failed_then_redirected_sample()
    parcel = normalize_parcel(raw)
    assert parcel["raw"] is raw
    assert len(parcel["raw"]["events"]) == 7
    assert parcel["raw"]["deliveryLocation"]["zip"] == "00000"
    assert parcel["raw"]["events"][3]["eventParameters"]


@pytest.mark.parametrize(
    ("country", "host"),
    [
        ("EE", "minu.omniva.ee"),
        ("LT", "mano.omniva.lt"),
        ("LV", "mana.omniva.lv"),
        ("FI", "minu.omniva.ee"),
        (None, "minu.omniva.ee"),
    ],
)
def test_tracking_url_follows_the_country(country, host):
    assert tracking_url("X", country) == f"https://{host}/track/X"


def test_tracking_url_needs_a_code():
    assert tracking_url(None) is None


def test_url_country_comes_from_the_destination_then_the_newest_scan():
    raw = delivered_sample()
    raw["deliveryLocation"]["countryCode"] = "LV"
    assert "mana.omniva.lv" in normalize_parcel(raw)["url"]
    assert "mano.omniva.lt" in normalize_parcel(in_progress_sample())["url"]


# ---------------------------------------------------------------------------
# sort_parcels_by_ts
# ---------------------------------------------------------------------------


def test_sort_parcels_ascending_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "planned_from": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "planned_from": None},
        {"barcode": "c", "planned_from": "2026-05-01T10:00:00Z"},
    ]
    ordered = [p["barcode"] for p in sort_parcels_by_ts(parcels, "planned_from")]
    assert ordered == ["c", "a", "b"]


def test_sort_parcels_descending_still_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "delivered_at": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "delivered_at": "nonsense"},
        {"barcode": "c", "delivered_at": "2026-05-01T10:00:00Z"},
    ]
    ordered = [
        p["barcode"]
        for p in sort_parcels_by_ts(parcels, "delivered_at", descending=True)
    ]
    assert ordered == ["a", "c", "b"]


# ---------------------------------------------------------------------------
# apply_delivered_filter
# ---------------------------------------------------------------------------


def _entry(filter_type: str, amount: int) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_DELIVERED_FILTER_TYPE: filter_type,
            CONF_DELIVERED_FILTER_AMOUNT: amount,
        },
        unique_id=DOMAIN,
    )


def _delivered_pair() -> list[dict]:
    now = datetime.now(UTC)
    return [
        {"barcode": "RECENT", "delivered_at": (now - timedelta(days=1)).isoformat()},
        {"barcode": "OLD", "delivered_at": (now - timedelta(days=30)).isoformat()},
    ]


def test_delivered_filter_by_days():
    kept = apply_delivered_filter(_delivered_pair(), _entry("days", 7))
    assert [p["barcode"] for p in kept] == ["RECENT"]


def test_delivered_filter_by_count():
    parcels = _delivered_pair()
    assert apply_delivered_filter(parcels, _entry("parcels", 1)) == parcels[:1]


def test_delivered_filter_keeps_unparseable_timestamp():
    """Better to show a parcel with a broken date than to silently drop it."""
    parcels = [{"barcode": "WEIRD", "delivered_at": "nonsense"}]
    assert apply_delivered_filter(parcels, _entry("days", 7)) == parcels
