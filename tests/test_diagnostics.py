"""Tests for Omniva diagnostics."""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.omniva.diagnostics import (
    TO_REDACT,
    async_get_config_entry_diagnostics,
)
from custom_components.omniva.parcels import normalize_parcel

from .payloads import ACTIVE_CODE, envelope, event, pickup_sample, place


async def test_diagnostics_redacts_and_counts(hass):
    """Diagnostics get pasted into public issues — nothing identifying may survive."""
    entry = MagicMock()
    entry.options = {"parcels": [{"tracking_code": ACTIVE_CODE}]}
    entry.runtime_data.coordinator.current_tier_minutes = 15
    entry.runtime_data.coordinator.update_interval = timedelta(minutes=15)
    raw = pickup_sample()
    raw["events"].append(
        event(
            "TRT_SHIPMENT_RECIPIENT_NOTIFICATION_EVENT",
            "2026-03-01T10:00:00Z",
            "Sent to Jane Doe",
            place(),
            [{"name": "PHONE", "value": "+37200000000"}],
        )
    )
    parcel = normalize_parcel(raw, include_history=True)
    entry.runtime_data.coordinator.data = [parcel]
    entry.runtime_data.coordinator.delivered = [
        normalize_parcel(envelope(state="DELIVERED", destination=place()))
    ]
    entry.runtime_data.coordinator.delivered_codes = set()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["counts"] == {
        "incoming_active": 1,
        "delivered": 1,
        "skipped_from_fetch": 0,
    }
    assert result["polling"] == {
        "tier_minutes": 15,
        "update_interval_seconds": 900.0,
        "suspended": False,
    }
    assert result["entry_options"]["parcels"][0]["tracking_code"] == "**REDACTED**"
    incoming = result["incoming"][0]
    for field in ("barcode", "raw_status", "pickup_point", "url", "raw"):
        assert incoming[field] == "**REDACTED**"
    assert incoming["history"][0]["raw_status"] == "**REDACTED**"
    # non-identifying fields survive, or the diagnostics would be useless
    assert incoming["status"] == "at_pickup_point"
    assert incoming["history"][0]["timestamp"]

    dumped = str(result)
    for secret in (
        ACTIVE_CODE,
        "Example",
        "Jane Doe",
        "+37200000000",
        "00000",
        "Wording",
    ):
        assert secret not in dumped


@pytest.mark.parametrize(
    "key",
    ["shipmentBarcode", "deliveryLocation", "location", "eventParameters", "eventName"],
)
async def test_redaction_names_the_stored_payload_fields(key):
    """The list is spelled as the reply spells it, even though ``raw`` goes whole."""
    assert key in TO_REDACT


async def test_diagnostics_reports_suspended_polling(hass):
    """update_interval None (Section 2.1's full stop) must be visible, not just absent."""
    entry = MagicMock()
    entry.options = {"parcels": []}
    entry.runtime_data.coordinator.current_tier_minutes = None
    entry.runtime_data.coordinator.update_interval = None
    entry.runtime_data.coordinator.data = []
    entry.runtime_data.coordinator.delivered = []

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["polling"] == {
        "tier_minutes": None,
        "update_interval_seconds": None,
        "suspended": True,
    }
