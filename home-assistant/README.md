# PyPLUS Home Assistant Integration

A HACS-compatible custom integration for [Home Assistant](https://www.home-assistant.io/) that connects to your local [PyPLUS](https://github.com/msberends/pyplus) instance.

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations** → three-dot menu → **Custom repositories**
3. Add the repository URL and select **Integration** as the category
4. Search for "PyPLUS" and install
5. Restart Home Assistant

### Manual

Copy `custom_components/pyplus/` to your Home Assistant `config/custom_components/` directory and restart.

## Setup

1. In PyPLUS, go to **Instellingen** and generate an API key under **API-toegang**
2. In Home Assistant, go to **Settings** → **Devices & Services** → **Add Integration**
3. Search for "PyPLUS" and enter your PyPLUS URL and API key

## Entities

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.pyplus_weekmenu_today` | Sensor | Today's planned dinner dish |
| `sensor.pyplus_weekmenu_filled` | Sensor | Number of filled weekmenu slots |
| `sensor.pyplus_autopilot_status` | Sensor | Latest autopilot plan status |
| `sensor.pyplus_staples_count` | Sensor | Number of staple products |
| `switch.pyplus_autopilot` | Switch | Toggle autopilot on/off |

## Services

| Service | Description |
|---------|-------------|
| `pyplus.set_weekmenu_slot` | Assign a dish to a weekmenu slot |
| `pyplus.trigger_autopilot` | Generate a new autopilot plan |
| `pyplus.sync_now` | Force a data refresh |
