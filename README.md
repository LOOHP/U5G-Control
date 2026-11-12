# U5G Control for Home Assistant

An experimental Home Assistant custom integration for controlling radio modes and band preferences on Ubiquiti U5G-class cellular modems over local SSH.

## What it creates

Each configured physical modem is represented as a Home Assistant hub device. Every SIM observed in that modem becomes a persistent child device named from its SPN and the last four ICCID digits, for example `O2 [5244]`. Removing a SIM makes its entities unavailable without deleting its saved profile; reinserting it reactivates the same device.

Radio preferences are isolated per SIM. Inserting a remembered SIM restores its saved policy. A newly observed SIM starts from the modem baseline captured before the integration's first managed write instead of inheriting the previously inserted SIM's masks.

Each supported SIM child exposes:

- **Enable 5G SA** and **Enable 5G NSA** switches.
- Separate switches for the LTE, SA, and NSA bands selected during setup.
- Actual SA/NSA activity binary sensors.
- Carrier, current mode, primary band, RSRP, RSRQ, and SINR sensors.
- Up to three LTE and three 5G component-carrier sensors. Each carrier's band is the state and every statistic reported by the modem is exposed as an attribute. Unused carriers report `Not connected`.
- A channel-width sensor for every component carrier, normalized to MHz when the firmware reports bandwidth.
- Restore default and restore previous configuration buttons.

The four mode combinations map to:

| SA | NSA | Applied policy |
|---|---|---|
| Off | Off | LTE only |
| Off | On | LTE + NSA, with LTE fallback |
| On | Off | SA only |
| On | On | LTE + NR with SA and NSA allowed |

When SA or NSA is disabled, the integration preserves the user's selected bands but writes a hidden placeholder mask. The default placeholder is n79. Setup asks for the placeholder before band selection and removes it from the NR switch choices, so it cannot also be exposed as a toggle.

## Installation

### Manual

1. Copy `custom_components/u5g_control` into the Home Assistant `/config/custom_components/` directory.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration**.
4. Search for **U5G Control**.
5. Enter the Device SSH credentials from UniFi Network.
6. Choose an unused NR band for the disabled-mode placeholder from the modem-populated `n1`, `n3`, etc. dropdown.
7. Choose which LTE, SA, and NSA bands should be exposed as switches. No switches are selected by default, and the placeholder band is excluded from the NR lists.

For the broadest band list in the setup screen, restore the modem's automatic radio preferences before adding the integration. The modem reports its current masks rather than a guaranteed immutable capability list; a modem already locked to one band may therefore initially expose only that band. The list can be expanded later through **Configure** after restoring automatic preferences.

### HACS custom repository

Once this folder is hosted in a Git repository, add its URL to HACS as an **Integration** custom repository and install **U5G Control**.

## UniFi prerequisites

- Enable Device SSH Authentication in UniFi Network.
- Home Assistant must be able to reach the U5G management IP locally.
- Use the device SSH username/password, not the console's root credentials.

## Reconfiguration

Open the integration entry and select **Configure** to:

- Add or remove exposed band switches.
- Change the disabled-mode placeholder band.
- Change the polling interval.
- Enable automatic policy reapplication after UniFi configuration drift.
- Forget inactive SIM profiles.

Inactive SIMs can also be deleted directly from their Home Assistant device page. The active SIM and modem hub cannot be deleted this way. Forgetting a SIM removes only its Home Assistant profile; reinserting it creates a fresh child device.

## Important limitations

- This uses undocumented Ubiquiti `uiwwand-ctl` behavior and may break after firmware updates.
- “NSA enabled” means NSA is permitted. The modem may remain LTE-only when no compatible EN-DC combination is available.
- On firmware which rejects empty NR masks, disabling a mode uses a configured placeholder band. Ensure that band is not deployed by the serving network.
- U5G models have different capabilities. NSA entities are only created when the modem reports NSA bands during setup.
- The first observed SSH host key is saved automatically and later changes are rejected. There is no interactive fingerprint-confirmation step because this integration is intended for locally managed modems.
- Changing radio preferences can interrupt cellular service. Maintain local management access.

## Privacy

The integration needs the full ICCID internally because `set-radio-pref` requires it. ICCIDs are stored only in Home Assistant's private storage and are never exposed as entity state. Child device identifiers use a SHA-256-derived value. Diagnostics redact ICCIDs, cell IDs, PCIs, and radio channel identifiers.
