"""Omniva public tracking API client.

The contract the coordinator relies on:

* ``async_get_parcel`` returns the raw reply on success,
* returns ``None`` when the carrier does not know the tracking code (a normal,
  expected state — never an error),
* raises :class:`OmnivaApiError` for anything else, with ``status_code`` set on
  a non-2xx response and ``retry_after`` set when the carrier's own
  ``Retry-After`` header on a 429 could be parsed as seconds — the coordinator's
  backoff reads both,
* lets ``aiohttp.ClientError`` propagate untouched — ``DataUpdateCoordinator``
  already wraps those into ``UpdateFailed``.
"""

from __future__ import annotations

from typing import Any

import aiohttp

from .const import TRACKING_API_URL
from .parcels import warn_unseen

# Whoever holds one of these can open the parcel machine or door. ``raw`` ends up
# in attributes, events and the recorder, so they must never get that far.
_OPENING_CODE_KEYS = frozenset({"openingCode", "accessCode", "doorCode"})


def _without_opening_codes(value: Any) -> Any:
    """Return the reply with every opening code removed, at any depth."""
    if isinstance(value, dict):
        return {
            key: _without_opening_codes(item)
            for key, item in value.items()
            if key not in _OPENING_CODE_KEYS
        }
    if isinstance(value, list):
        return [_without_opening_codes(item) for item in value]
    return value


class OmnivaApiError(Exception):
    """Raised when an Omniva API call returns an unexpected response."""

    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Store the status code and the ``Retry-After`` header, if any."""
        super().__init__(f"Omniva API request failed: {detail}")
        self.detail = detail
        self.status_code = status_code
        self.retry_after = retry_after


class OmnivaApiClient:
    """Client for the public Omniva tracking endpoint.

    No authentication: the endpoint is keyed on the tracking code alone.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with an aiohttp session."""
        self._session = session

    async def async_get_parcel(self, tracking_code: str) -> dict[str, Any] | None:
        """Fetch one parcel's tracking details.

        Returns the reply for a known parcel, or ``None`` when the code is
        unknown or the reply is about another parcel. Any other reply, a block
        page included, raises :class:`OmnivaApiError` so the last good data
        stays; network errors propagate as ``aiohttp.ClientError``.
        """
        url = TRACKING_API_URL.format(tracking_code=tracking_code)
        async with self._session.get(url) as response:
            if response.status == 429:
                retry_after_header = response.headers.get("Retry-After")
                try:
                    retry_after = (
                        float(retry_after_header) if retry_after_header else None
                    )
                except ValueError:
                    retry_after = None  # an HTTP-date, not seconds; let the caller's own backoff handle it
                raise OmnivaApiError(
                    "HTTP 429", status_code=429, retry_after=retry_after
                )
            if response.status != 200:
                raise OmnivaApiError(
                    f"HTTP {response.status}", status_code=response.status
                )
            try:
                # content_type=None: a block page must fail on its body here,
                # the same way whatever content type it claims.
                payload = await response.json(content_type=None)
            except ValueError as err:
                raise OmnivaApiError("unparseable body") from err

        if not isinstance(payload, dict):
            raise OmnivaApiError("unexpected body (not a JSON object)")
        if not payload:
            return None
        if "shipmentBarcode" not in payload:
            raise OmnivaApiError("unexpected body (no shipment number)")
        if payload["shipmentBarcode"] != tracking_code:
            warn_unseen("reply", "other_barcode")
            return None
        return _without_opening_codes(payload)
