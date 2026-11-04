"""Diagnostics support for the Omniva parcel tracker integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import OmnivaConfigEntry

# Diagnostics are pasted into public issues, so redact anything that
# identifies a person, an address or a specific parcel. ``raw`` goes as a whole:
# a scan's wording and parameters can hold a recipient's contact details.
TO_REDACT = {
    # canonical fields we publish ourselves
    "tracking_code",
    "barcode",
    "sender",
    "receiver",
    "raw_status",
    "pickup_point",
    "url",
    "raw",
    # carrier payload fields
    "shipmentBarcode",
    "deliveryLocation",
    "location",
    "eventParameters",
    "eventName",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OmnivaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for the Omniva config entry."""
    coordinator = entry.runtime_data.coordinator

    return {
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "counts": {
            "incoming_active": len(coordinator.data or []),
            "delivered": len(coordinator.delivered or []),
            "skipped_from_fetch": len(coordinator.delivered_codes),
        },
        "polling": {
            "tier_minutes": coordinator.current_tier_minutes,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "suspended": coordinator.update_interval is None,
        },
        "incoming": async_redact_data(coordinator.data or [], TO_REDACT),
        "delivered": async_redact_data(coordinator.delivered or [], TO_REDACT),
    }
