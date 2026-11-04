"""Sample Omniva API payloads shared by the test modules.

Scrubbed: tracking codes, event ids, dates, postcodes and place names are made up;
the structure, codes and wording are real.
"""

from __future__ import annotations

ACTIVE_CODE = "JJEE00000000000000001"
DELIVERED_CODE = "CC000000000EE"


def place(point_type: str = "PARCEL_MACHINE", country: str = "LT") -> dict:
    """A scan's site, or the recipient's chosen one."""
    return {
        "zip": "00000",
        "locationName": f"Example {point_type.lower()}",
        "servicePointTypeCode": point_type,
        "countryCode": country,
        "translations": {},
    }


def event(
    code: str,
    date: str,
    name: str | None = None,
    location: dict | None = None,
    parameters: list | None = None,
) -> dict:
    """One scan. A scan without a site has no ``location`` key at all."""
    scan = {
        "eventId": 1000,
        "eventCode": code,
        "eventName": name if name is not None else f"Wording of {code}",
        "eventDate": date,
        "eventParameters": parameters or [],
    }
    if location is not None:
        scan["location"] = location
    return scan


def envelope(
    code: str = ACTIVE_CODE,
    *,
    events: list | None = None,
    state: str = "IN_PROGRESS",
    channel: str = "COURIER",
    destination: dict | None = None,
    returning: bool = False,
) -> dict:
    """The reply around a list of scans."""
    reply = {
        "shipmentBarcode": code,
        "currentDeliveryChannel": channel,
        "returningShipment": returning,
        "customsDeclarationRequired": False,
        "events": events if events is not None else [],
        "currentStateCode": state,
    }
    if destination is not None:
        reply["deliveryLocation"] = destination
    return reply


def in_progress_sample(code: str = ACTIVE_CODE) -> dict:
    """A courier parcel on its way, scans out of order and clocks of mixed precision."""
    return envelope(
        code,
        events=[
            event(
                "TRT_SHIPMENT_ARRIVED_TO_PO",
                "2026-03-02T10:34:48.476Z",
                location=place("WORKSTATION"),
            ),
            event(
                "TRT_SHIPMENT_ARRIVED_TO_PO",
                "2026-03-02T10:37:41.030731900Z",
                location=place("DISTRIBUTION_POINT"),
            ),
            event("TRT_SHIPMENT_REGISTERED", "2026-03-01T11:44:21.410118500Z"),
            event(
                "TRT_SHIPMENT_PICKED_UP_BY_COURIER",
                "2026-03-01T12:20:44.721Z",
                parameters=[{"name": "SHIPMENT_SCANNED", "value": "0"}],
            ),
        ],
    )


def delivered_sample(code: str = DELIVERED_CODE) -> dict:
    """An old item: the service trimmed its history to the delivery."""
    return envelope(
        code,
        events=[
            event(
                "TRT_SHIPMENT_DELIVERED",
                "2026-03-05T12:50:22.097006600Z",
                "Shipment delivered",
                place(),
            )
        ],
        state="DELIVERED",
        channel="PARCEL_MACHINE",
        destination=place(),
    )


def active_sample(code: str = ACTIVE_CODE) -> dict:
    """An out-for-delivery courier parcel."""
    sample = in_progress_sample(code)
    sample["events"].insert(
        0,
        event(
            "TRT_SHIPMENT_COURIER_DELIVERY_STARTED",
            "2026-03-03T05:18:04.005620800Z",
            "The shipment has been handed over to the courier",
            place("DISTRIBUTION_POINT"),
        ),
    )
    return sample


def pickup_sample(code: str = ACTIVE_CODE) -> dict:
    """A parcel waiting in a parcel machine."""
    sample = in_progress_sample(code)
    sample["events"].insert(
        0,
        event(
            "TRT_SHIPMENT_STORED_IN_PM",
            "2026-03-03T09:01:41.600404400Z",
            "Shipment is ready for collection from the parcel machine",
            place(),
        ),
    )
    sample.update(
        currentDeliveryChannel="PARCEL_MACHINE",
        deliveryLocation=place(),
        currentStateCode="IN_PARCEL_MACHINE",
    )
    return sample


def failed_then_redirected_sample(code: str = ACTIVE_CODE) -> dict:
    """A full journey: failed courier rounds, a redirect, a machine, collection."""
    worked = place("DISTRIBUTION_POINT")
    attempt = [
        {"name": "TASK_EVENT_MEASURE_ID", "value": "0"},
        {"name": "TASK_EVENT_REASON_CODE_ID", "value": "0"},
    ]
    return envelope(
        code,
        events=[
            event("TRT_SHIPMENT_REGISTERED", "2026-03-01T11:44:21.410118500Z"),
            event(
                "TRT_SHIPMENT_STORED_IN_PM",
                "2026-03-14T09:01:41.600404400Z",
                location=place(),
            ),
            event(
                "TRT_SHIPMENT_DELIVERED",
                "2026-03-17T16:29:18Z",
                "Shipment delivered",
                place(),
            ),
            event(
                "TRT_SHIPMENT_REDIRECTION",
                "2026-03-13T09:25:40.465536700Z",
                parameters=[{"name": "REDIRECTION_REASON_CODE_ID", "value": "0"}],
            ),
            event(
                "TRT_SHIPMENT_FAILED_DELIVERY_ATTEMPT",
                "2026-03-08T12:01:30.619Z",
                location=worked,
                parameters=attempt,
            ),
            event(
                "TRT_SHIPMENT_COURIER_DELIVERY_STARTED",
                "2026-03-08T05:31:04.802803Z",
                location=worked,
            ),
            event(
                "TRT_SHIPMENT_ARRIVED_TO_PO",
                "2026-03-02T10:34:48.476Z",
                location=place("WORKSTATION"),
            ),
        ],
        state="DELIVERED",
        channel="PARCEL_MACHINE",
        destination=place(),
    )
