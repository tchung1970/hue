# hue

A command-line tool to control Philips Hue lights through the
[Bridge](https://www.philips-hue.com/en-us/p/hue-bridge/046677458478)'s local
CLIP v2 API.

```text
$ hue
Usage: hue [OPTIONS] [COMMAND] [ARGS]...

  Control Philips Hue lights via the Bridge's local API.

Commands:
  list        List lights, rooms, scenes, or schedules.
  change      Change a light, room, or scene.
  rename      Rename a light or room.
  schedule    CLIP v1 — add / delete / list (CLI schedules).
  automation  CLIP v2 — list only (Hue app automations).
  bridge      Show Bridge details and pairing status.
  setup       Pair with a Bridge and save its application key.
  version     Show the version.
  help        Show this help message.
```

## 100% local — no cloud, no account, no internet

`hue` talks **only** to your Hue Bridge on your own network. The Philips cloud is
never contacted — not for discovery, not for control, not ever:

- **Discovery** uses local **SSDP/UPnP** multicast on your LAN (not Philips'
  cloud discovery service).
- **Control** goes straight to the Bridge's local API over your LAN.
- **No Philips account, no internet** required after the one-time pairing.
- Your usage data never leaves your network.

## Requirements

- **Python 3.9+**
- A **Philips Hue Bridge** (the square v2 bridge) on the same LAN, plus Hue bulbs
- Python packages, installed automatically by `pip`:
  - [`click`](https://pypi.org/project/click/) ≥ 8.1 — command-line interface
  - [`requests`](https://pypi.org/project/requests/) ≥ 2.31 — HTTP to the Bridge

No system packages, no Hue developer account, no internet.

## Install

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

To run `hue` from anywhere, symlink the console script onto your PATH:

```sh
ln -sf "$PWD/.venv/bin/hue" ~/bin/hue   # assuming ~/bin is on PATH
```

(The symlink points into `.venv`; if you rebuild the venv, re-run `pip install -e .`.)

## Setup (one time)

Pair with the Bridge. You'll be asked to press the round link button on top of
the Bridge:

```sh
hue setup                  # finds the Bridge via local SSDP
```

Credentials are saved to `~/.config/hue/config.json` (owner-readable only).
If you're already paired, `hue setup` says so and does nothing.

## Commands

The command list is shown at the top of this README (and by `hue` / `hue help`).
Every command prints friendly guidance (with relevant listings) when run with
missing arguments, instead of a raw error. The sections below cover the main ones.

### Listing

```sh
hue list lights            # bulbs grouped by room: state, brightness, model, color temp
hue list rooms             # rooms
hue list scenes            # scenes grouped by room
hue list schedules         # CLI schedules

hue list room ThomasRoom       # the bulbs in one room
hue list light AllisonLight-1  # one light's state
hue list scenes ThomasRoom     # scenes belonging to a room
```

`list` tolerates singular/plural, case, and typos (`hue list roms` asks "did you
mean rooms?").

### Changing

`change` is the main verb. The state is `on`, `off`, a `0-100` brightness, or
`warm`/`cool` (color temperature). After a change it prints the target's
resulting status. White-only bulbs warn that warm/cool isn't supported.

```sh
hue change room ThomasRoom on
hue change room ThomasRoom 50          # 50% brightness
hue change room AllisonRoom warm       # ~2700K (color-temp bulbs only)
hue change room AllisonRoom cool       # ~5000K
hue change light AllisonLight-1 on --ct 4000   # precise Kelvin
hue change scene LivingRoom Bright     # activate a scene
```

### Scheduling vs automations

There are two independent systems on the Bridge:

- **`hue schedule`** — **CLIP v1** time rules created by *this tool*. They run on
  the Bridge 24/7 but do **not** appear in the Hue app.
- **`hue automation`** — **CLIP v2** automations created in the *Hue app*
  (schedules, motion, wake/sleep). Read-only here; the CLI only lists them.

```text
$ hue automation
[on ]  Lights Out            Schedule          12:00 AM, Every day
[on ]  Wake Up               Schedule          8:00 AM–10:00 AM, Weekdays

$ hue schedule
  1  [enabled]  everyday at 11:00 PM  — hue-cli ThomasRoom off
  2  [enabled]  everyday at 7:00 AM   — hue-cli ThomasRoom on
```

Creating schedules:

```sh
hue schedule add ThomasRoom off --at 11pm           # daily (--at takes 11pm or 23:00)
hue schedule add ThomasRoom on --at 7am --days weekdays --dim 60
hue schedule add ThomasRoom off --in 30             # timer: fire once in 30 min
hue schedule add ThomasRoom off --at 10:30pm --date 2026-07-04   # one-time
hue schedule list
hue schedule delete <id>

hue automation             # list the app's automations
```

`--days` accepts `everyday` (default), `weekdays`, `weekend`, or a comma list
(`mon,wed,fri`). `--dim N` sets brightness (1-100) when turning on. Times are
shown in AM/PM.

## License

[MIT](LICENSE) © 2026 Thomas Chung
