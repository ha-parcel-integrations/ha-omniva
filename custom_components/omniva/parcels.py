"""Canonical parcel shape, status mapping and list helpers.

Everything in this module is a **pure function** — no I/O, no Home Assistant
objects beyond the config entry's options. That keeps the carrier-specific
mapping apart from the coordinator and makes it unit-testable without HA.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    HISTORY_MAX_EVENTS,
    TRACKING_HOSTS,
    TRACKING_URL,
    ParcelStatus,
)

_LOGGER = logging.getLogger(__name__)

# Where users report a status we do not map yet.
#
# The ``?template=`` parameter matters: without it the link opens a blank form,
# and the report comes back missing the version and the log line we need.
NEW_ISSUE_URL = (
    "https://github.com/ha-parcel-integrations/ha-omniva/issues/new"
    "?template=unrecognised_status.yml"
)

# Scan codes and state codes never collide, so they share one map.
_STATUS_MAP: dict[str, ParcelStatus] = {
    **dict.fromkeys(
        (
            "TRT_SHIPMENT_REGISTERED",
            "TRT_SHIPMENT_REGISTERED_IN_OMNIVA",
            "REGISTERED",
            "REGISTERED_IN_OMNIVA",
        ),
        ParcelStatus.REGISTERED,
    ),
    **dict.fromkeys(
        (
            "TRT_SHIPMENT_HANDOVER_TO_PM",
            "TRT_SHIPMENT_HANDOVER_TO_PO",
            "TRT_SHIPMENT_PICKED_UP_BY_COURIER",
            "TRT_SHIPMENT_EMA",
            "TRT_SHIPMENT_DEPARTED_FROM_PM",
            "TRT_SHIPMENT_ARRIVED_TO_PO",
            "TRT_SHIPMENT_SORTED",
            "TRT_SHIPMENT_REDIRECTION",
            "TRT_SHIPMENT_MOVEMENT_RESTORED",
            "TRT_SHIPMENT_RETURN_CANCELLED",
            "TRT_SHIPMENT_COURIER_DELIVERY_CANCELLED",
            "TRT_SHIPMENT_RELEASED_FROM_CUSTOMS",
            "TRT_SHIPMENT_EMB",
            "TRT_SHIPMENT_EMC",
            "TRT_SHIPMENT_EMD",
            "TRT_SHIPMENT_EMF",
            "TRT_SHIPMENT_EMG",
            "TRT_SHIPMENT_EMJ",
            "TRT_SHIPMENT_EDA",
            "TRT_SHIPMENT_EDC",
            "TRT_SHIPMENT_EDD",
            "TRT_SHIPMENT_EDE",
            "TRT_SHIPMENT_EDF",
            "CARGO_SHIPMENT_ARRIVED_TO_TRANSIT_HUB",
            "CARGO_SHIPMENT_DEPARTED_FROM_TRANSIT_HUB",
            "CARGO_SHIPMENT_IN_TRANSIT_TO_DESTINATION_COUNTRY",
            "CARGO_SHIPMENT_ARRIVING_TO_DESTINATION_COUNTRY",
            "CARGO_SHIPMENT_ARRIVED_TO_DESTINATION_COUNTRY",
            "CARGO_SHIPMENT_ARRIVED_TO_CUSTOMS_CLEARANCE_HUB",
            "CARGO_SHIPMENT_RELEASED_FROM_CUSTOMS",
            "CARGO_SHIPMENT_HANDOVER_FROM_LINEHAUL_EVENT",
            "CARGO_SHIPMENT_HANDED_TO_LAST_MILE",
            "CARGO_SHIPMENT_ARRIVED_TO_SORTING",
            "CARGO_SHIPMENT_DEPARTED_FROM_SORTING",
            "CARGO_SHIPMENT_ARRIVED_TO_LAST_DELIVERY_OFFICE",
            "CARGO_SHIPMENT_DEPARTED_FROM_RETURNING_COUNTRY",
            "CARGO_SHIPMENT_ARRIVED_TO_RETURNING_COUNTRY_HUB",
            "TRT_SHIPMENT_TAKEN_TO_CUSTOMS",
            "TRT_SHIPMENT_HELD_IN_CUSTOMS",
            "TRT_SHIPMENT_ASSIGN_CUSTOMS_INSPECTION",
            "TRT_SHIPMENT_ARRIVAL_CUSTOMS_NOTIFICATION",
            "TRT_SHIPMENT_CD_REMINDER_NOTIFICATION",
            "TRT_SHIPMENT_CD_ADD_PAYMENT_NOTIFICATION",
            "TRT_SHIPMENT_CD_ADD_PAYMENT_REMINDER_NOTIFICATION",
            "TRT_SHIPMENT_CUSTOMS_PAYMENT_REQ_REMINDER",
            "TRT_SHIPMENT_EDB",
            "TRT_SHIPMENT_EME",
            "CARGO_SHIPMENT_PRESENTED_TO_CUSTOMS",
            "CARGO_SHIPMENT_HELD_IN_CUSTOMS",
            "IPS_POSTED_EMA",
            "IN_PROGRESS",
            "IN_TRANSIT",
            "IN_POST_OFFICE",
            "IN_LOGISTIC_CENTER",
            "IPS_DEPARTED_EMC",
            "IPS_ARRIVED_EMD",
            "RELEASED_FROM_CUSTOMS",
            "MOVEMENT_RESTORED",
            "RETURN_CANCELLED",
            "REDIRECTED",
            "IN_CUSTOMS",
            "TAKEN_TO_CUSTOMS",
        ),
        ParcelStatus.IN_TRANSIT,
    ),
    **dict.fromkeys(
        (
            "TRT_SHIPMENT_COURIER_DELIVERY_STARTED",
            "TRT_SHIPMENT_EDG",
            "CARGO_SHIPMENT_OUT_FOR_DELIVERY",
            "ON_COURIER_DELIVERY",
        ),
        ParcelStatus.OUT_FOR_DELIVERY,
    ),
    **dict.fromkeys(
        (
            "TRT_SHIPMENT_STORED_IN_PM",
            "TRT_SHIPMENT_ARRIVED_TO_FINAL_PO",
            "TRT_SHIPMENT_EDH",
            "CARGO_SHIPMENT_ARRIVED_TO_LAST_PICKUP_POINT",
            "READY_FOR_PICKUP",
            "IN_PARCEL_MACHINE",
        ),
        ParcelStatus.AT_PICKUP_POINT,
    ),
    **dict.fromkeys(
        (
            "TRT_SHIPMENT_FAILED_DELIVERY_ATTEMPT",
            "TRT_SHIPMENT_EMH",
            "CARGO_SHIPMENT_DELIVERY_FAILED",
            "TRT_SHIPMENT_CANCELLED",
            "TRT_SHIPMENT_MOVEMENT_STOPPED",
            "TRT_SHIPMENT_MISSING_IN_PM",
            "TRT_SHIPMENT_PREDECLARED_MISSING",
            "TRT_SHIPMENT_PROHIBIT",
            "TRT_SHIPMENT_EDX",
            "TRT_SHIPMENT_EXX",
            "CARGO_SHIPMENT_CANCELLED",
            "CARGO_SHIPMENT_DESTROYED",
            "CARGO_SHIPMENT_MISSING_IN_PM",
            "CARGO_SHIPMENT_NOT_ARRIVED_IN_BAG_EVENT",
            "FAILED_DELIVERY",
            "CANCELLED",
            "STOPPED",
            "MISSING",
            "LOST",
            "WRITTEN_OFF",
        ),
        ParcelStatus.PROBLEM,
    ),
    **dict.fromkeys(
        (
            "TRT_SHIPMENT_RETURN",
            "TRT_SHIPMENT_RETURNED_BY_CUSTOMER",
            "CARGO_SHIPMENT_POSTED_IN_RETURNING_COUNTRY",
            "CARGO_SHIPMENT_RETURNED",
            "RETURNED",
        ),
        ParcelStatus.RETURNING,
    ),
    **dict.fromkeys(
        (
            "TRT_SHIPMENT_DELIVERED",
            "TRT_SHIPMENT_EMI",
            "CARGO_SHIPMENT_DELIVERED",
            "DELIVERED",
        ),
        ParcelStatus.DELIVERED,
    ),
}

# Messages and bookkeeping, not movement: the parcel keeps the stage it had.
_NOTICE_CODES = frozenset(
    {
        "TRT_SHIPMENT_ARRIVAL_PM_NOTIFICATION",
        "TRT_SHIPMENT_ARRIVAL_PO_NOTIFICATION",
        "TRT_SHIPMENT_REMINDER_PM_NOTIFICATION",
        "TRT_SHIPMENT_REMINDER_PO_NOTIFICATION",
        "TRT_SHIPMENT_RECIPIENT_NOTIFICATION_EVENT",
        "TRT_COURIER_PRE_DELIVERY_RECIPIENT_NOTIFICATION",
        "TRT_COURIER_CALLED_TO_RECEIVER",
        "TRT_SHIPMENT_RECIPIENT_CONTACT_UPDATED",
        "TRT_SHIPMENT_DELIVERY_PARTNER_BARCODE_ASSIGNED",
        "CARGO_SHIPMENT_DELIVERY_PARTNER_BARCODE_ASSIGNED",
        "TRT_SHIPMENT_MEASURED",
        "TRT_SHIPMENT_DOC_RETURN_SENDER",
        "TRT_SHIPMENT_DECLARATION_CANCELLED",
    }
)

_RETURN_START_CODES = frozenset(
    {
        "TRT_SHIPMENT_RETURN",
        "TRT_SHIPMENT_RETURNED_BY_CUSTOMER",
        "CARGO_SHIPMENT_POSTED_IN_RETURNING_COUNTRY",
        "CARGO_SHIPMENT_RETURNED",
    }
)
_RETURN_CANCELLED_CODE = "TRT_SHIPMENT_RETURN_CANCELLED"
_RETURNED_STATE = "RETURNED"

# Unlike a generic "in progress", these say how the parcel ended. A scan we cannot
# read must not hide that behind an older scan.
_DEFINITE_STATES = frozenset({"DELIVERED", _RETURNED_STATE, "CANCELLED"})

# A recipient collects from these. Anything else (a sorting site, a home address)
# must never surface as the pickup point.
_PICKUP_POINT_TYPES = frozenset(
    {
        "PARCEL_MACHINE",
        "POST_OFFICE",
        "POST_STATION",
        "PICK_UP_POINT",
        "PARTNER_PICK_UP_POINT",
        "PARCEL_BOX",
    }
)
_KNOWN_POINT_TYPES = _PICKUP_POINT_TYPES | {
    "CLIENT",
    "DISTRIBUTION_POINT",
    "IMPC",
    "LOGISTIC_CENTER",
    "SUPPORT_POINT",
    "WAREHOUSE",
    "WORKSTATION",
}
_PICKUP_CHANNEL = "PARCEL_MACHINE"
_KNOWN_CHANNELS = frozenset({"COURIER", _PICKUP_CHANNEL})
_KNOWN_EVENT_PARAMETERS = frozenset(
    {
        "REDIRECTION_REASON_CODE_ID",
        "SHIPMENT_SCANNED",
        "TASK_EVENT_MEASURE_ID",
        "TASK_EVENT_REASON_CODE_ID",
    }
)

# What we have already warned about, so each is logged only once per HA session
# instead of on every poll.
_unmapped_statuses_logged: set[tuple[str, str]] = set()


def warn_unseen(kind: str, code: str) -> None:
    """Log something this integration has not seen yet, once, with an issue link.

    Only pass keys and codes: these lines get pasted into public issues.
    """
    if (kind, code) in _unmapped_statuses_logged:
        return
    _unmapped_statuses_logged.add((kind, code))
    _LOGGER.warning(
        "Unrecognised Omniva data — help us map it. Open an issue "
        "and paste this line: %s\n  %s=%s",
        NEW_ISSUE_URL,
        kind,
        code,
    )


def map_parcel_status(code: str | None) -> ParcelStatus:
    """Map a carrier state code to a :class:`ParcelStatus`.

    ``None`` reports ``unknown`` silently; an unrecognised code reports
    ``unknown`` with a one-shot warning.
    """
    return map_event_status(code) or ParcelStatus.UNKNOWN


def map_event_status(code: str | None) -> ParcelStatus | None:
    """Map a scan's code to a canonical status, or ``None``.

    Unmapped codes keep ``status: null`` on the history entry (rather than
    ``unknown``, so a consumer can tell "no mapping" from "mapped to unknown")
    and warn once.
    """
    if not code:
        return None
    mapped = _STATUS_MAP.get(code)
    if mapped is None:
        warn_unseen("status", code)
    return mapped


def _as_code(value: Any) -> str | None:
    """Return a code as text, or ``None``: one odd reply must not fail the whole poll."""
    if value is None or isinstance(value, str):
        return value
    warn_unseen("not_text", type(value).__name__)
    return None


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to an aware datetime, or ``None`` on failure.

    Naive values are treated as UTC so a list always sorts without crashing on
    a mixed set.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _read_scans(raw: dict) -> tuple[list[dict], bool]:
    """Return the scans oldest first, each with its status, and whether a return is on.

    A delivery while a return is under way reaches the sender, not the
    recipient, so it counts as ``returning``. The return flag on the reply
    stands in for a start scan the service has trimmed away.
    """
    events = raw.get("events")
    dated: list[tuple[datetime, dict]] = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        at = parse_iso(event.get("eventDate"))
        if at is None:
            warn_unseen("event_date", "unparseable")
            continue
        dated.append((at, event))
    dated.sort(key=lambda item: item[0])

    returning = (
        raw.get("returningShipment") is True
        or _as_code(raw.get("currentStateCode")) == _RETURNED_STATE
    )
    scans: list[dict] = []
    for at, event in dated:
        code = _as_code(event.get("eventCode"))
        if code in _RETURN_START_CODES:
            returning = True
        elif code == _RETURN_CANCELLED_CODE:
            returning = False
        notice = code in _NOTICE_CODES
        status = None if notice else map_event_status(code)
        if status is ParcelStatus.DELIVERED and returning:
            status = ParcelStatus.RETURNING
        scans.append(
            {
                "at": at,
                "status": status,
                "notice": notice,
                "text": event.get("eventName") or code,
                "location": _as_dict(event.get("location")),
            }
        )
    return scans, returning


def _resolve_status(raw: dict, scans: list[dict], returning: bool) -> ParcelStatus:
    """Newest scan that maps, else the state, else ``unknown``.

    The state is the fallback, not the lead: it stays a generic "in progress"
    while the scans already say the courier has the parcel. A definite state
    does lead when the newest scan is one we cannot read.
    """
    code = _as_code(raw.get("currentStateCode"))
    state = map_parcel_status(code)
    newest = next((scan for scan in reversed(scans) if not scan["notice"]), None)
    if code in _DEFINITE_STATES and newest is not None and newest["status"] is None:
        status = state
    else:
        status = next(
            (scan["status"] for scan in reversed(scans) if scan["status"] is not None),
            state,
        )
    # Scans on the way back read like any others. A problem still has to show.
    if returning and status is not ParcelStatus.PROBLEM:
        return ParcelStatus.RETURNING
    return status


def _warn_unseen_shapes(raw: dict) -> None:
    """Warn once per new channel, site type and parameter name, never their values."""
    channel = _as_code(raw.get("currentDeliveryChannel"))
    if channel and channel not in _KNOWN_CHANNELS:
        warn_unseen("delivery_channel", str(channel))
    events = raw.get("events")
    events = events if isinstance(events, list) else []
    rows = [event for event in events if isinstance(event, dict)]
    for location in (
        _as_dict(raw.get("deliveryLocation")),
        *(_as_dict(row.get("location")) for row in rows),
    ):
        point_type = _as_code(location.get("servicePointTypeCode"))
        if point_type and point_type not in _KNOWN_POINT_TYPES:
            warn_unseen("service_point_type", point_type)
    for row in rows:
        parameters = row.get("eventParameters")
        for parameter in parameters if isinstance(parameters, list) else []:
            name = _as_code(_as_dict(parameter).get("name"))
            if name and name not in _KNOWN_EVENT_PARAMETERS:
                warn_unseen("event_parameter", name)


def _point_name(location: dict) -> str | None:
    if _as_code(location.get("servicePointTypeCode")) in _PICKUP_POINT_TYPES:
        return location.get("locationName") or None
    return None


def _pickup_point(raw: dict, scans: list[dict], status: ParcelStatus) -> str | None:
    """Name the site the parcel waits at or was collected from.

    A parcel machine further back can be where the sender dropped it off, so the
    scans only count while they are about waiting or collection.
    """
    if status not in (ParcelStatus.AT_PICKUP_POINT, ParcelStatus.DELIVERED):
        return None
    name = _point_name(_as_dict(raw.get("deliveryLocation")))
    if name:
        return name
    for scan in reversed(scans):
        if scan["status"] is None:
            continue
        if scan["status"] not in (ParcelStatus.AT_PICKUP_POINT, ParcelStatus.DELIVERED):
            return None
        name = _point_name(scan["location"])
        if name:
            return name
    return None


def build_history(
    scans: list[dict], *, max_events: int = HISTORY_MAX_EVENTS
) -> list[dict]:
    """Build the canonical ``history`` list from :func:`_read_scans`' result.

    Each entry is ``{timestamp, status, raw_status}`` — identical across all
    suite carriers, and top-level (not under ``raw``) so it survives the
    aggregator's ``strip_raw()``. Oldest → newest, capped to the most recent
    ``max_events``.
    """
    entries = [
        {
            "timestamp": scan["at"].isoformat(),
            "status": scan["status"],
            "raw_status": scan["text"],
        }
        for scan in scans
        if not scan["notice"]
    ]
    return entries[-max_events:]


def tracking_url(tracking_code: str | None, country: str | None = None) -> str | None:
    """Construct the consumer tracking deep-link for a parcel."""
    if not tracking_code:
        return None
    host = TRACKING_HOSTS.get(country or "", TRACKING_HOSTS["EE"])
    return TRACKING_URL.format(host=host, tracking_code=tracking_code)


def normalize_parcel(raw: dict, *, include_history: bool = False) -> dict:
    """Return a carrier-agnostic parcel dict with the payload under ``raw``.

    The **keys of the returned dict are the contract**: every carrier in the
    suite returns exactly these, in this order. A field the carrier does not
    expose stays ``None``.
    """
    tracking_code = raw.get("shipmentBarcode")
    scans, returning = _read_scans(raw)
    _warn_unseen_shapes(raw)
    status = _resolve_status(raw, scans, returning)
    delivered = status is ParcelStatus.DELIVERED

    delivered_at = None
    if delivered:
        delivered_at = next(
            (
                scan["at"].isoformat()
                for scan in reversed(scans)
                if scan["status"] is ParcelStatus.DELIVERED
            ),
            None,
        )

    destination = _as_dict(raw.get("deliveryLocation"))
    country = _as_code(destination.get("countryCode")) or next(
        (
            code
            for scan in reversed(scans)
            if (code := _as_code(scan["location"].get("countryCode")))
        ),
        None,
    )
    to_pickup_point = (
        raw.get("currentDeliveryChannel") == _PICKUP_CHANNEL
        or _as_code(destination.get("servicePointTypeCode")) in _PICKUP_POINT_TYPES
    )

    return {
        "carrier": "Omniva",
        "barcode": tracking_code,
        "sender": None,
        "receiver": None,
        "status": status,
        "raw_status": scans[-1]["text"]
        if scans
        else _as_code(raw.get("currentStateCode")),
        "delivered": delivered,
        "delivered_at": delivered_at,
        "planned_from": None,
        "planned_to": None,
        "pickup": status is ParcelStatus.AT_PICKUP_POINT
        or (to_pickup_point and not returning),
        "pickup_point": _pickup_point(raw, scans, status),
        "url": tracking_url(tracking_code, country),
        "weight": None,
        "dimensions": None,
        "history": build_history(scans) if include_history else None,
        "raw": raw,
    }


def sort_parcels_by_ts(
    parcels: list[dict], key_field: str, *, descending: bool = False
) -> list[dict]:
    """Return normalised parcels sorted by the ISO timestamp at ``key_field``.

    The suite's sort contract: incoming/outgoing ascending on ``planned_from``,
    delivered descending on ``delivered_at``. Parcels whose value is missing or
    unparseable always sort to the end, regardless of ``descending``.
    """
    with_ts: list[tuple[datetime, dict]] = []
    without_ts: list[dict] = []
    for parcel in parcels:
        parsed = parse_iso(parcel.get(key_field))
        if parsed is None:
            without_ts.append(parcel)
        else:
            with_ts.append((parsed, parcel))
    with_ts.sort(key=lambda item: item[0], reverse=descending)
    return [parcel for _, parcel in with_ts] + without_ts


def apply_delivered_filter(parcels: list[dict], entry: ConfigEntry) -> list[dict]:
    """Trim the delivered list per the entry's retention option.

    ``parcels`` must already be sorted newest-first. ``days`` keeps deliveries
    from the last N days (an unparseable ``delivered_at`` is kept rather than
    silently dropped); the ``parcels`` type keeps the N most recent. Parcels
    stay *tracked* either way — this only controls what the delivered sensor
    shows.
    """
    options = entry.options
    filter_type = options.get(CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE)
    amount = int(
        options.get(CONF_DELIVERED_FILTER_AMOUNT, DEFAULT_DELIVERED_FILTER_AMOUNT)
    )
    if filter_type == "days":
        cutoff = datetime.now(UTC) - timedelta(days=amount)
        return [
            parcel
            for parcel in parcels
            if (parsed := parse_iso(parcel.get("delivered_at"))) is None
            or parsed >= cutoff
        ]
    return parcels[:amount]
