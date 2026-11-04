# Omniva Parcel Tracker

[![Release](https://img.shields.io/github/v/release/ha-parcel-integrations/ha-omniva.svg)](https://github.com/ha-parcel-integrations/ha-omniva/releases)
[![Downloads](https://img.shields.io/github/downloads/ha-parcel-integrations/ha-omniva/total.svg)](https://github.com/ha-parcel-integrations/ha-omniva/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 📦 Part of [**ha-parcel-integrations**](https://ha-parcel-integrations.github.io/), a family of package-tracking integrations for Home Assistant that all publish the same parcel format, statuses and events, so they plug into cross-carrier automations and the optional [Parcel Aggregator](https://github.com/ha-parcel-integrations/ha-parcel-aggregator). Browse the other carriers on the website.
>
> 💬 Questions or feedback? Join the discussion on the [Home Assistant community](https://community.home-assistant.io/t/packages-postnl-dhl-nl-dpd-and-gls-parcel-integration/112433/).

A custom Home Assistant integration that tracks your [Omniva](https://www.omniva.ee) parcels in Estonia, Latvia and Lithuania, whether they go to a parcel machine, a post office or your door. No account is needed — you enter the tracking code yourself.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Options](#options)
- [Removal](#removal)
- [Sensors](#sensors)
- [Parcel status reference](#parcel-status-reference)
- [Events](#events)
- [Services](#services)
- [Examples](#examples)
- [Debugging](#debugging)
- [Troubleshooting](#troubleshooting)
- [Related integrations](#related-integrations)
- [Disclaimer](#disclaimer)
- [Contributing](#contributing)
- [License](#license)

## Features

- Track any number of Omniva parcels by tracking code — no account needed
- Per-parcel sensor with the canonical status (`registered` / `in_transit` / `out_for_delivery` / `delivered` / …), the carrier's own status text, the pickup point and a tracking deep-link
- Summary sensors: incoming parcels, parcels on their way to or waiting at a pickup point, recently delivered parcels
- `omniva.track_parcel` / `omniva.untrack_parcel` services, so a dashboard button can add a parcel
- Events + device triggers for no-code automations (parcel registered, status changed, delivered)
- Opt-in per-parcel status history
- Manual refresh button and a diagnostic last-update sensor

## Requirements

- Home Assistant 2025.12 or newer
- An Omniva parcel and its tracking code from the shipping confirmation or
  the delivery message: `JJEE` followed by digits or letters, or a postal item
  code such as `CC000000000EE` — no account needed

## Installation

### HACS (recommended)

Click the button below to open this repository in HACS, then install **Omniva**:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ha-parcel-integrations&repository=ha-omniva&category=integration)

Or add it by hand: in HACS, choose the three-dot menu → **Custom repositories**, add `https://github.com/ha-parcel-integrations/ha-omniva` as an **Integration** and install **Omniva**.

Restart Home Assistant if HACS asks you to.

### Manual

Copy `custom_components/omniva` into your `config/custom_components/` folder and restart Home Assistant.

## Configuration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=omniva)

Add the integration via **Settings → Devices & Services → Add Integration → Omniva** and choose **Tracking codes**. There is nothing to fill in: the hub is created immediately (Omniva tracking needs no account).

Then add parcels via the integration's **Configure** dialog, the [`omniva.track_parcel`](#services) service, or a [dashboard button](examples/dashboards/add_parcel_card.yaml). The tracking code is on your shipping confirmation or the delivery message.

## Options

Open **Configure** on the integration entry:

| Section | Option | Default | Description |
|---|---|---|---|
| Parcels | Add / remove | — | Manage the tracked tracking codes. Changes apply immediately, no restart. |
| Delivered parcels | Filter by / amount | last 7 days | How long delivered parcels stay visible on the delivered sensor. |
| Parcel history | Include status history | off | Adds a `history` attribute per parcel with each status update. |

Polling isn't one of these settings: the integration polls on a dynamic,
status-driven schedule with nothing to configure.

## Dynamic polling

Polling isn't a setting here — the integration adjusts its own cadence to
what your tracked parcels are actually doing:

- **Quiet hours** — no polling between 00:00–06:00 local time, aside from one
  catch-up check at each end of that window (around midnight and around 6
  AM), so an overnight update is never missed.
- **Hot (every 15 minutes)** — while any tracked parcel is out for delivery
  today, starting an hour before its delivery window opens (or immediately if
  no window is known yet).
- **Normal (every 45 minutes)** — for anything else still on its way.
- **Fully paused** — once every tracked parcel has been delivered, or nothing
  is tracked at all, polling stops until you add a parcel back (adding one
  always triggers an immediate check, regardless of the pause).
- A small, fixed per-hub offset is added on top, so not every Omniva
  hub out there polls at exactly the same second.

Omniva reports no expected delivery window, so a parcel that is out for delivery is always polled on the hot cadence until the next scan. A parcel on its way back to the sender is never treated as delivered, so it keeps being polled until you remove it.

## Removal

Standard HA removal applies: **Settings → Devices & Services → Omniva → ⋮ → Delete**. Nothing is stored on Omniva's side.

## Sensors

| Entity | Description |
|---|---|
| `sensor.omniva_incoming_parcels` | Number of active tracked parcels, full list under the `parcels` attribute |
| `sensor.omniva_parcel_<code>` | One per tracked parcel; state is the canonical status, attributes carry the full normalised parcel |
| `sensor.omniva_next_delivery` | Earliest expected delivery moment. Omniva gives no delivery estimate, so this stays empty |
| `sensor.omniva_en_route_to_pickup_point` | Incoming parcels on their way to a pickup point that have not arrived yet |
| `sensor.omniva_awaiting_pickup` | Incoming parcels that are ready to collect at a pickup point |
| `sensor.omniva_delivered_parcels` | Recently delivered parcels (see the retention option) |
| `calendar.omniva_deliveries` | Read-only calendar of expected deliveries. Omniva gives no delivery estimate, so this stays empty |
| `sensor.omniva_last_successful_update` | Diagnostic: when Omniva was last polled successfully |

A delivered parcel moves from its per-parcel sensor to the delivered sensor automatically.

## Parcel status reference

The `status` field is the carrier-agnostic enum shared by the whole integration family:

| Status | Meaning |
|---|---|
| `registered` | Announced by the sender, not handed over to Omniva yet |
| `in_transit` | On its way through Omniva's network, customs included |
| `out_for_delivery` | With the courier today |
| `at_pickup_point` | Waiting for you in a parcel machine or at a post office |
| `delivered` | Delivered to you, or collected |
| `returning` | Going back to the sender, and still this once it has reached them |
| `problem` | A failed delivery attempt, or a cancelled, stopped or missing parcel; the next scan moves it on |
| `unknown` | Omniva does not know this code yet, or nothing it reports can be mapped yet |

The carrier's own human-readable text is always available as `raw_status`.

## Events

The integration fires these on the event bus (also available as device triggers on the Omniva device):

| Event | When |
|---|---|
| `omniva_parcel_registered` | A new parcel appears in the active list |
| `omniva_parcel_status_changed` | A parcel's canonical status changes (`old_status` / `new_status` in the payload), except the final hop to delivered |
| `omniva_parcel_delivered` | A parcel is delivered |
| `omniva_parcel_delivery_time_changed` | The expected delivery window changes. Omniva gives none today, so this does not fire |

Every payload is the full normalised parcel plus the hub's `device_id`. Events are suppressed on the first refresh after start-up.

## Services

| Service | Fields | Description |
|---|---|---|
| `omniva.track_parcel` | `tracking_code` | Start tracking a parcel |
| `omniva.untrack_parcel` | `tracking_code` | Stop tracking a parcel |

## Examples

Ready-to-paste automations and dashboard snippets live in [`examples/`](examples/), including tracking a new parcel straight from a dashboard.

### Community Lovelace cards

Third-party cards that work with this integration's sensors:

- [jonisnet/hki-parcels-card](https://github.com/jonisnet/hki-parcels-card)
- [klaptafel/ha-package-tracker-card](https://github.com/klaptafel/ha-package-tracker-card)

## Debugging

```yaml
logger:
  logs:
    custom_components.omniva: debug
```

## Troubleshooting

- **A parcel shows `unknown`** — Omniva does not know the code yet, or it is wrong, or the item is so old that Omniva has dropped it. A new parcel picks up automatically once it is known.
- **A status logs "Unrecognised Omniva data"** — please [open an issue](https://github.com/ha-parcel-integrations/ha-omniva/issues/new?template=unrecognised_status.yml) with the logged line so the mapping can be extended.

## Related integrations

This integration is part of [**ha-parcel-integrations**](https://ha-parcel-integrations.github.io/) — a family of
parcel-carrier integrations that all publish the same canonical parcel format,
statuses and events.

- [**Parcel Aggregator**](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) rolls every installed carrier
  up into one set of sensors.
- Browse [the organisation](https://ha-parcel-integrations.github.io/) for the current list of supported carriers.

## Disclaimer

This is an independent, community-built project. It is not affiliated with, endorsed by, sponsored by, or supported by Omniva, Home Assistant, or any other third party referenced in this project. Please don't contact Omniva for support with this integration.

All third-party trademarks, trade names, product names, logos, and other brand assets are the property of their respective owners. References to them are solely to identify the relevant carrier or service and do not imply affiliation, sponsorship, or endorsement. Nothing in this project grants or implies any licence or right to use third-party brand assets.

This integration may rely on public, unofficial, or undocumented carrier interfaces, accessed without an account. These may change or be withdrawn without notice and may be subject to Omniva's terms. Data is sent only to Omniva's own services or those of its group; this project operates no servers of its own. You are responsible for ensuring that your use complies with applicable law and those terms. Use is at your own risk; see the [licence](LICENSE) for warranty limitations.

## Contributing

Pull requests and issues are welcome. Please open an issue before
submitting a large change.

## License

[MIT](LICENSE)
