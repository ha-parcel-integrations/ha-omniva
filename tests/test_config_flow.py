"""Tests for the Omniva config and options flow."""

import json
from pathlib import Path

from homeassistant.data_entry_flow import AbortFlow
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.omniva import config_flow
from custom_components.omniva.config_flow import (
    normalize_tracking_code,
    valid_tracking_code,
)
from custom_components.omniva.const import (
    ACCOUNT_ISSUE_URL,
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    CONF_INCLUDE_HISTORY,
    CONF_PARCELS,
    CONF_SOURCE,
    CONF_TRACKING_CODE,
    DOMAIN,
    SOURCE_ACCOUNT,
    SOURCE_TRACKING,
)


def test_normalize_tracking_code_strips_and_uppercases():
    assert normalize_tracking_code("example 123-456") == "EXAMPLE123456"
    assert normalize_tracking_code("") == ""
    assert normalize_tracking_code(None) == ""


def test_valid_tracking_code_accepts_any_non_empty_code():
    assert valid_tracking_code("EXAMPLE123456")
    assert valid_tracking_code("ABC")
    assert valid_tracking_code("A" * 31)
    assert not valid_tracking_code("")


async def test_user_flow_opens_on_the_source_menu(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "menu"
    assert result["step_id"] == "user"
    assert result["menu_options"] == [SOURCE_ACCOUNT, SOURCE_TRACKING]


async def test_tracking_choice_creates_hub_without_input(hass):
    """No account, no postcode — the entry is created straight away."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": SOURCE_TRACKING}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "Omniva"
    assert result["data"] == {CONF_SOURCE: SOURCE_TRACKING}
    assert result["result"].unique_id == DOMAIN
    assert result["options"][CONF_PARCELS] == []


async def test_tracking_step_aborts_when_a_hub_appeared_meanwhile(hass):
    """Two open dialogs get past the manifest's check; the second stops here."""
    flow = config_flow.OmnivaConfigFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.flow_id = "second-dialog"
    flow.context = {"source": "user"}
    MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN).add_to_hass(hass)

    with pytest.raises(AbortFlow) as err:
        await flow.async_step_tracking()
    assert err.value.reason == "already_configured"


async def test_account_choice_explains_and_creates_nothing(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": SOURCE_ACCOUNT}
    )
    assert result["type"] == "abort"
    assert result["reason"] == "account_unavailable"
    assert result["description_placeholders"] == {"issue_url": ACCOUNT_ISSUE_URL}
    assert hass.config_entries.async_entries(DOMAIN) == []


def _keys(value: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, item in value.items():
        if isinstance(item, dict):
            keys |= _keys(item, f"{prefix}{key}.")
        else:
            keys.add(f"{prefix}{key}")
    return keys


@pytest.mark.parametrize("language", ["et", "lt", "lv", "nl"])
def test_every_language_has_exactly_the_english_keys(language):
    folder = Path(config_flow.__file__).parent / "translations"
    english = json.loads((folder / "en.json").read_text(encoding="utf-8"))
    other = json.loads((folder / f"{language}.json").read_text(encoding="utf-8"))
    assert _keys(other) == _keys(english)


def test_strings_equal_the_english_translation():
    folder = Path(config_flow.__file__).parent
    strings = json.loads((folder / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((folder / "translations/en.json").read_text(encoding="utf-8"))
    assert strings == english


@pytest.mark.parametrize("language", ["en", "et", "lt", "lv", "nl"])
def test_account_text_takes_its_link_from_the_placeholder(language):
    path = Path(config_flow.__file__).parent / "translations" / f"{language}.json"
    text = json.loads(path.read_text(encoding="utf-8"))["config"]["abort"][
        "account_unavailable"
    ]
    assert "{issue_url}" in text
    assert "https://" not in text


async def test_second_hub_rejected(hass):
    MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "abort"
    # single_config_entry in the manifest aborts before the flow runs.
    assert result["reason"] == "single_instance_allowed"


def _hub(parcels: list[dict]) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        options={CONF_PARCELS: parcels},
    )


def _settings_input(
    *,
    history=False,
    filter_type="days",
    amount=7,
) -> dict:
    """Build the settings-form submission."""
    return {
        CONF_DELIVERED_FILTER_TYPE: filter_type,
        CONF_DELIVERED_FILTER_AMOUNT: amount,
        CONF_INCLUDE_HISTORY: history,
    }


async def _open_options_step(hass, entry, step_id: str):
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "menu"
    assert result["menu_options"] == ["parcels", "settings"]
    return await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": step_id}
    )


async def test_options_add_parcel(hass):
    entry = _hub([])
    entry.add_to_hass(hass)

    result = await _open_options_step(hass, entry, "parcels")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracking_codes": ["example123456"]}
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == [{CONF_TRACKING_CODE: "EXAMPLE123456"}]


async def test_options_add_code_with_separators(hass):
    """Pasted codes with spaces/dashes are sanitised like the consumer site."""
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await _open_options_step(hass, entry, "parcels")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracking_codes": ["example-123 456"]}
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == [{CONF_TRACKING_CODE: "EXAMPLE123456"}]


async def test_options_accepts_any_non_empty_code(hass):
    """A short/odd-shaped code is accepted — formats vary too much to gate on."""
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await _open_options_step(hass, entry, "parcels")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracking_codes": ["abc"]}
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == [{CONF_TRACKING_CODE: "ABC"}]


async def test_options_de_duplicates_tracking_codes(hass):
    entry = _hub([{CONF_TRACKING_CODE: "EXAMPLE111111"}])
    entry.add_to_hass(hass)
    result = await _open_options_step(hass, entry, "parcels")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracking_codes": ["EXAMPLE111111", "example111111"]}
    )
    assert result["data"][CONF_PARCELS] == [{CONF_TRACKING_CODE: "EXAMPLE111111"}]


async def test_options_remove_parcel(hass):
    entry = _hub(
        [
            {CONF_TRACKING_CODE: "EXAMPLE111111"},
            {CONF_TRACKING_CODE: "EXAMPLE222222"},
        ]
    )
    entry.add_to_hass(hass)
    result = await _open_options_step(hass, entry, "parcels")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracking_codes": ["EXAMPLE222222"]}
    )
    assert result["type"] == "create_entry"
    codes = {p[CONF_TRACKING_CODE] for p in result["data"][CONF_PARCELS]}
    assert codes == {"EXAMPLE222222"}


async def test_options_can_clear_the_tracked_code_list(hass):
    entry = _hub([{CONF_TRACKING_CODE: "EXAMPLE111111"}])
    entry.add_to_hass(hass)
    result = await _open_options_step(hass, entry, "parcels")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracking_codes": []}
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_PARCELS] == []


async def test_options_changes_history_and_delivered(hass):
    entry = _hub([])
    entry.add_to_hass(hass)
    result = await _open_options_step(hass, entry, "settings")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        _settings_input(
            history=True,
            filter_type="parcels",
            amount=5,
        ),
    )
    assert result["type"] == "create_entry"
    assert result["data"][CONF_INCLUDE_HISTORY] is True
    assert result["data"][CONF_DELIVERED_FILTER_TYPE] == "parcels"
    assert result["data"][CONF_DELIVERED_FILTER_AMOUNT] == 5
