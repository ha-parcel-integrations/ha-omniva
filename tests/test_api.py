"""Tests for the Omniva API client."""

import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.omniva.api import OmnivaApiClient, OmnivaApiError

from .payloads import in_progress_sample

CODE = "JJEE00000000000000001"


def _session_returning(status: int, body: object = None) -> MagicMock:
    response = AsyncMock()
    response.status = status
    if isinstance(body, str):
        response.json = AsyncMock(side_effect=json.JSONDecodeError("x", body, 0))
    else:
        response.json = AsyncMock(return_value=body)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.get = MagicMock(return_value=ctx)
    return session


async def test_get_parcel_returns_the_reply_on_success():
    reply = in_progress_sample(CODE)
    session = _session_returning(200, reply)

    assert await OmnivaApiClient(session).async_get_parcel(CODE) == reply
    assert session.get.call_args[0][0].endswith(f"/{CODE}")


async def test_get_parcel_returns_none_on_empty_object():
    """An unknown code is a normal state, and answers HTTP 200."""
    assert (
        await OmnivaApiClient(_session_returning(200, {})).async_get_parcel(CODE)
        is None
    )


async def test_get_parcel_returns_none_for_another_parcels_reply(caplog):
    """A reply naming another number must never show as this parcel."""
    client = OmnivaApiClient(_session_returning(200, in_progress_sample("OTHER")))

    assert await client.async_get_parcel(CODE) is None
    assert await client.async_get_parcel(CODE) is None

    assert caplog.text.count("reply=other_barcode") == 1
    assert "OTHER" not in caplog.text
    assert CODE not in caplog.text


async def test_get_parcel_raises_when_reply_names_no_number():
    """A malformed reply is a failed fetch, so the last good data stays."""
    client = OmnivaApiClient(_session_returning(200, {"message": "Try later"}))
    with pytest.raises(OmnivaApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_removes_opening_codes_at_any_depth_and_keeps_the_rest():
    reply = in_progress_sample(CODE)
    reply["openingCode"] = "111111"
    reply["deliveryLocation"] = {"locationName": "Machine", "accessCode": "222222"}
    reply["events"][0]["doorCode"] = "333333"

    result = await OmnivaApiClient(_session_returning(200, reply)).async_get_parcel(
        CODE
    )

    text = json.dumps(result)
    for secret in ("111111", "222222", "333333", "openingCode", "accessCode"):
        assert secret not in text
    assert "doorCode" not in text
    assert result["deliveryLocation"] == {"locationName": "Machine"}
    assert len(result["events"]) == len(reply["events"])
    assert result["currentStateCode"] == reply["currentStateCode"]


@pytest.mark.parametrize("status", [403, 404, 500, 502, 503])
async def test_get_parcel_raises_on_error_status(status):
    """A block page or a server error is never "not found"."""
    client = OmnivaApiClient(_session_returning(status, "<html>Blocked</html>"))
    with pytest.raises(OmnivaApiError) as err:
        await client.async_get_parcel(CODE)
    assert err.value.status_code == status


async def test_get_parcel_raises_on_html_block_page_with_status_200():
    client = OmnivaApiClient(_session_returning(200, "<html>Blocked</html>"))
    with pytest.raises(OmnivaApiError) as err:
        await client.async_get_parcel(CODE)
    assert "Blocked" not in str(err.value)


async def test_get_parcel_raises_on_non_object_body():
    client = OmnivaApiClient(_session_returning(200, ["not", "a", "dict"]))
    with pytest.raises(OmnivaApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_429_with_retry_after():
    session = _session_returning(429, {})
    session.get.return_value.__aenter__.return_value.headers = {"Retry-After": "120"}
    with pytest.raises(OmnivaApiError) as err:
        await OmnivaApiClient(session).async_get_parcel(CODE)
    assert err.value.status_code == 429
    assert err.value.retry_after == 120.0


async def test_get_parcel_ignores_a_date_shaped_retry_after():
    session = _session_returning(429, {})
    session.get.return_value.__aenter__.return_value.headers = {
        "Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"
    }
    with pytest.raises(OmnivaApiError) as err:
        await OmnivaApiClient(session).async_get_parcel(CODE)
    assert err.value.retry_after is None


async def test_get_parcel_propagates_network_error():
    """ClientError is left alone — DataUpdateCoordinator already wraps it."""
    session = MagicMock()
    session.get = MagicMock(side_effect=aiohttp.ClientError("boom"))
    client = OmnivaApiClient(session)
    with pytest.raises(aiohttp.ClientError):
        await client.async_get_parcel(CODE)
