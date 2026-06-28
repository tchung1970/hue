# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python CLI (`hue`) that controls Philips Hue lights by talking to the Bridge's
**local CLIP v2 API** over the LAN. **Strictly LAN-only — the Philips cloud is
never contacted** (discovery uses local SSDP, control uses the local API). Keep
it that way: no `discovery.meethue.com`, no remote/cloud endpoints.

## Commands (dev)

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e .          # editable install

hue <command>             # console script (entry point is hue.cli:main)
python -m hue <command>   # equivalent
```

No tests or linter are configured. Reinstall (`pip install -e .`) only if the
entry point in `pyproject.toml` changes.

## User-facing command surface

`list`, `change`, `rename`, `schedule`, `automation`, `bridge`, `setup`,
`version`, `help`. There are intentionally **no** `on`/`off`/`bt`/`ct`/`color`/
`scene`/`discover` commands — they were folded into `change` (state =
on/off/0-100/warm/cool, scene via `change scene`) and `bridge` (was `discover`).

## Architecture

Flow is **CLI → config → bridge client → CLIP v2/v1 HTTP**. Modules:

- `hue/cli.py` — Click command group; the only layer doing user I/O. Commands
  build a `HueBridge` via `_connect()` (exits "run hue setup" if unpaired) and
  route errors through `_fail()`. `main()` wraps `cli.main()` (see gotchas).
- `hue/bridge.py` — the API client. Three concerns:
  - **Discovery + pairing** — `discover_bridges()` does **local SSDP/UPnP
    multicast** (no cloud). `bridge_public_config()` reads `/api/0/config`
    unauthenticated. `pair()` uses legacy `/api`, raises `LinkButtonNotPressed`
    (error type 101) until the button is pressed.
  - **Control** (`get`/`put` + resolvers) — modern `/clip/v2/resource/*` with the
    `hue-application-key` header.
  - **Schedules** (`add_schedule`, `_v1`) — CLIP **v1** `/schedules`.
- `hue/config.py` — persists `{bridge_ip, app_key, client_key}` to
  `~/.config/hue/config.json` (override `$HUE_CONFIG`); `save()` chmods 0o600.
- `hue/color.py` — `kelvin_to_mirek` (used by `--ct`/warm/cool). `rgb_to_xy`/
  `hex_to_xy` are legacy (no `color` command).
- `hue/models.py` — `model_id` → friendly description; "Warm-to-Cool" prefix
  marks color-temperature-capable models.
- `hue/schedule.py` — pure builders for the v1 `localtime` string, day-mask math,
  `normalize_time` (accepts 24h and AM/PM), and `clock_12h`/`describe_localtime`
  (render times in AM/PM).

## Two scheduling systems (don't conflate them)

- **`schedule`** = CLIP **v1** `/schedules`, created by this tool. Run on the
  Bridge but are **invisible in the Hue app**.
- **`automation`** = CLIP **v2** `behavior_instance`, created in the Hue app.
  `automation` is **read-only** (lists them); `_list_automations` filters out
  `_NON_AUTOMATION_SCRIPTS` (e.g. "Hue Accessories" button configs). Creating v2
  automations is unimplemented (needs `behavior_instance` + a recipe).

## Things that will bite you

- **TLS verification is intentionally disabled** (`verify=False`). The Bridge's
  self-signed cert is bound to its bridge-id, not its LAN IP. Don't "fix" it.
- **Two name fields per bulb.** A light has `metadata.name`; the **device** that
  owns it has its own. The Hue app shows the *device* name, so `rename` updates
  **both** or the change won't appear in the app.
- **grouped_light can't do color temperature.** `set_state` applies color/ct
  per member light, skipping bulbs without `color_temperature` (white-only).
  `color_temp_capable()` drives the white-only warning so the CLI doesn't claim
  "changed" when nothing changed.
- **Brightness is 0–100 (float)** in CLIP v2; the v1 schedule API uses 1–254
  (`schedule.brightness_to_v1`).
- **v1 schedules: do NOT send `autodelete`.** Recent firmware (≥1.77) rejects it
  ("parameter not available"); `add_schedule` omits it and relies on the Bridge's
  default. `recycle` is still accepted.
- **Rooms vs zones differ:** a room's `children` are *devices* (→ lights via
  `owner`); a zone's `children` are *lights*. See `_group_member_lights`.
- **Read-after-write lag.** `change` sleeps ~0.4s before reading status back.
- **`main()` wrapper.** Prints a trailing blank line after every invocation and
  swallows BrokenPipeError when piped into `head`.
- **Customized help.** `OrderedGroup` fixes command order and puts Commands above
  Options; `--version`/`--help` are exposed as the `version`/`help` commands
  (`add_help_option=False`, `invoke_without_command=True`).
- **Never bulk-delete schedules when verifying.** Delete only the specific ids
  you created — a blanket "delete all" will wipe the user's real schedules.
