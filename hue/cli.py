"""The ``hue`` command-line interface."""

from __future__ import annotations

import os
import sys
import time
from difflib import get_close_matches

import click
import requests

from . import __author__, __date__, __version__
from .bridge import (
    HueBridge,
    HueError,
    LinkButtonNotPressed,
    bridge_public_config,
    discover_bridges,
    pair,
)
from .color import kelvin_to_mirek
from .config import Config
from .models import describe_model
from .schedule import action_body, build_localtime, describe_localtime


def _connect() -> HueBridge:
    """Build a HueBridge from saved config, or exit with guidance."""
    cfg = Config.load()
    if not cfg.is_paired:
        click.echo("Not paired with a Bridge yet. Run:  hue setup", err=True)
        sys.exit(1)
    return HueBridge(cfg.bridge_ip, cfg.app_key)  # type: ignore[arg-type]


def _fail(message: str) -> None:
    click.echo(f"error: {message}", err=True)
    sys.exit(1)


class OrderedGroup(click.Group):
    """A Click group that lists commands in a preferred order instead of
    alphabetically. Commands not listed fall to the end, alphabetically."""

    ORDER = [
        "list", "change", "rename",
        "schedule", "automation", "bridge", "setup", "version", "help",
    ]

    def list_commands(self, ctx):
        rank = {name: i for i, name in enumerate(self.ORDER)}
        return sorted(super().list_commands(ctx), key=lambda n: (rank.get(n, len(rank)), n))

    def format_options(self, ctx, formatter):
        # Only show Commands — no Options section (version/help are commands).
        self.format_commands(ctx, formatter)


def _echo_help(ctx: click.Context) -> None:
    click.echo(ctx.get_help())


@click.group(
    cls=OrderedGroup,
    add_help_option=False,  # exposed as the `help` command instead
    invoke_without_command=True,
    help="Control Philips Hue lights via the Bridge's local API.",
)
@click.pass_context
def cli(ctx: click.Context) -> None:
    if ctx.invoked_subcommand is None:
        _echo_help(ctx)
        ctx.exit()


@cli.command()
def version() -> None:
    """Show the version."""
    click.echo(f"hue, version {__version__}")
    click.echo(f"by {__author__} on {__date__}")


@cli.command(name="help")
@click.pass_context
def help_cmd(ctx: click.Context) -> None:
    """Show this help message."""
    _echo_help(ctx.parent)


@cli.command(name="bridge", short_help="Show Bridge details and pairing status.")
def bridge_cmd() -> None:
    """Show the Hue Bridge on your network: IP, model, firmware, and whether
    this tool is paired with it."""
    saved = Config.load()
    bridges = discover_bridges()  # local SSDP; no cloud
    if not bridges and saved.bridge_ip:
        bridges = [{"internalipaddress": saved.bridge_ip}]  # fall back to saved IP
    if not bridges:
        click.echo("No bridges found. Make sure the Bridge is powered and on your LAN.")
        return
    for i, b in enumerate(bridges):
        ip = b.get("internalipaddress", "?")
        if i > 0:
            click.echo("")  # blank line between multiple bridges
        try:
            cfg = bridge_public_config(ip)
        except requests.RequestException:
            click.echo(f"ip:       {ip}")
            click.echo("(could not read bridge details)")
            continue
        click.echo(f"name:     {cfg.get('name', '?')}")
        click.echo(f"model:    {cfg.get('modelid', '?')}")
        click.echo(f"firmware: {cfg.get('swversion', '?')}")
        click.echo(f"ip:       {ip}")
        click.echo(f"api:      {cfg.get('apiversion', '?')}")
        click.echo(f"paired:   {_pairing_status(saved, ip)}")


def _pairing_status(saved: Config, ip: str) -> str:
    """Whether this tool's saved key works against the bridge at ``ip``."""
    if not saved.app_key:
        return f"no — run: hue setup --ip {ip}"
    try:
        if HueBridge(ip, saved.app_key).get("bridge"):
            return "yes (this API tool)"
        return f"no — run: hue setup --ip {ip}"
    except requests.exceptions.HTTPError:
        return f"no, saved key rejected — run: hue setup --ip {ip}"
    except requests.RequestException:
        return "unknown (unreachable)"


@cli.command()
@click.option("--ip", help="Bridge IP address (skips network discovery).")
@click.option("--force", is_flag=True, help="Re-pair even if already paired.")
def setup(ip: str | None, force: bool) -> None:
    """Pair with a Bridge and save its application key.

    You'll be prompted to press the round link button on top of the Bridge.
    """
    saved = Config.load()
    if saved.is_paired and not force:
        try:
            if HueBridge(saved.bridge_ip, saved.app_key).get("bridge"):  # type: ignore[arg-type]
                click.echo(f"Already paired with the Bridge at {saved.bridge_ip}.")
                click.echo("Run 'hue setup --force' to pair again.")
                return
        except (requests.RequestException, HueError):
            click.echo("Saved pairing isn't responding — re-pairing...")

    if not ip:
        click.echo("Looking for your Bridge on the local network...")
        bridges = discover_bridges()
        if not bridges:
            _fail("no bridge found on the network. Retry with: hue setup --ip <bridge-ip>")
        ip = bridges[0]["internalipaddress"]
        click.echo(f"Using bridge at {ip}")

    click.echo("Press the round link button on top of the Bridge, then press Enter.")
    click.prompt("Ready", default="", show_default=False, prompt_suffix="")

    # Poll briefly in case the user pressed Enter a moment before the button.
    deadline = time.time() + 30
    while True:
        try:
            result = pair(ip)
            break
        except LinkButtonNotPressed:
            if time.time() >= deadline:
                _fail("link button was not pressed in time. Run setup again.")
            click.echo("Waiting for link button...")
            time.sleep(2)
        except (requests.RequestException, HueError) as exc:
            _fail(str(exc))

    cfg = Config(bridge_ip=ip, app_key=result["username"], client_key=result.get("clientkey"))
    path = cfg.save()
    click.echo(f"Paired. Saved credentials to {path}")


def _ct_label(light: dict) -> str:
    """Current color temperature as ``2700K warm`` / ``5000K cool``, or '' when
    the light has no active color temperature (white-only, or in color mode)."""
    ct = light.get("color_temperature") or {}
    mirek = ct.get("mirek")
    if not mirek:
        return ""
    kelvin = round(1_000_000 / mirek)
    word = "warm" if kelvin <= 3500 else "cool" if kelvin >= 4500 else "neutral"
    return f"{kelvin}K {word}"


def _light_line(light: dict, model: str | None = None) -> str:
    """Format one light as ``[on ]  100%  Name`` (plus model and current color
    temperature when available)."""
    name = light.get("metadata", {}).get("name", "?")
    state = "on " if light.get("on", {}).get("on", False) else "off"
    bri = light.get("dimming", {}).get("brightness")
    bri_str = f"  {round(bri):>3}%" if bri is not None else ""
    ct = _ct_label(light)
    ct_str = f"  {ct}" if ct else ""
    if model:
        return f"[{state}]{bri_str}  {name:<14}  {model}{ct_str}"
    return f"[{state}]{bri_str}  {name}{ct_str}"


def _device_models(bridge: HueBridge) -> dict:
    """Map device id -> model id, for labelling lights by bulb model."""
    return {d["id"]: d.get("product_data", {}).get("model_id", "?") for d in bridge.get("device")}


def _model_str(light: dict, device_models: dict) -> str:
    """``LWA003  (A19 Hue White)`` style label for a light's bulb model."""
    model = device_models.get(light.get("owner", {}).get("rid"), "?")
    desc = describe_model(model)
    return f"{model}  ({desc})" if desc else model


def _list_lights(bridge: HueBridge) -> None:
    # Map each device -> its room name, so lights can be grouped by room. A room's
    # `children` are the devices it contains; a light's `owner` is its device.
    device_room = {
        child["rid"]: room.get("metadata", {}).get("name", "?")
        for room in bridge.rooms()
        for child in room.get("children", [])
        if child.get("rtype") == "device"
    }
    device_model = _device_models(bridge)

    by_room: dict[str, list[str]] = {}
    for light in bridge.lights():
        room = device_room.get(light.get("owner", {}).get("rid"), "(no room)")
        by_room.setdefault(room, []).append(_light_line(light, _model_str(light, device_model)))

    for room in sorted(by_room):
        click.echo(f"{room}:")
        for line in sorted(by_room[room]):
            click.echo(f"  {line}")


def _list_rooms(bridge: HueBridge) -> None:
    # Zones are still resolvable everywhere, just not listed (none defined).
    for group in bridge.rooms():
        click.echo(group.get("metadata", {}).get("name", "?"))


def _echo_target_lights(bridge: HueBridge, canonical: str, name: str, header: str = "\nLights in") -> list:
    """Print the bulbs in a room/zone (or a single light) with model labels.
    Returns the lights found (empty list if the name didn't resolve)."""
    try:
        lights = (
            bridge._group_member_lights(name) if canonical == "room"
            else bridge.get("light", bridge.resolve_target(name)[1])
        )
    except (requests.RequestException, HueError):
        lights = []
    if lights:
        models = _device_models(bridge)
        click.echo(f"{header} {name}:")
        for light in sorted(lights, key=lambda l: l.get("metadata", {}).get("name", "")):
            click.echo(f"  {_light_line(light, _model_str(light, models))}")
    return lights


def _echo_scenes_in_room(bridge: HueBridge, room_name: str) -> None:
    needle = room_name.strip().lower()
    group_names = {
        g["id"]: g.get("metadata", {}).get("name", "?")
        for g in bridge.rooms() + bridge.zones()
    }
    names = sorted(
        s.get("metadata", {}).get("name", "?")
        for s in bridge.scenes()
        if group_names.get(s.get("group", {}).get("rid"), "").lower() == needle
    )
    if not names:
        _fail(f"no scenes for room {room_name!r}")
    click.echo(f"Scenes in {room_name}:")
    for n in names:
        click.echo(f"  {n}")


def _list_scenes(bridge: HueBridge) -> None:
    # Scenes share names across rooms ("Relax" exists per room), so group them
    # by the room/zone each belongs to via its `group` reference.
    group_names = {
        g["id"]: g.get("metadata", {}).get("name", "?")
        for g in bridge.rooms() + bridge.zones()
    }
    by_room: dict[str, list[str]] = {}
    for scene in bridge.scenes():
        room = group_names.get(scene.get("group", {}).get("rid"), "(unknown)")
        by_room.setdefault(room, []).append(scene.get("metadata", {}).get("name", "?"))
    for room in sorted(by_room):
        click.echo(f"{room}:")
        for name in sorted(by_room[room]):
            click.echo(f"  {name}")


_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday"}
_WEEKEND = {"saturday", "sunday"}
_ALL_DAYS = _WEEKDAYS | _WEEKEND
_DAY_ORDER = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _fmt_clock(time_point: dict) -> str:
    t = (time_point or {}).get("time_point", {}).get("time", {})
    h, m = t.get("hour", 0), t.get("minute", 0)
    period = "AM" if h < 12 else "PM"
    return f"{h % 12 or 12}:{m:02d} {period}"


def _fmt_days(days: list) -> str:
    s = set(days)
    if s == _ALL_DAYS:
        return "Every day"
    if s == _WEEKDAYS:
        return "Weekdays"
    if s == _WEEKEND:
        return "Weekend"
    return ", ".join(d[:3].capitalize() for d in _DAY_ORDER if d in s) or "—"


# Behavior scripts that are accessory/device configs, not "automations" in the
# Hue app's Automations-tab sense — excluded from the automation listing.
_NON_AUTOMATION_SCRIPTS = {"Hue Accessories"}


def _list_automations(bridge: HueBridge) -> None:
    """List the Hue app's automations (CLIP v2 behavior_instance). Read-only —
    these are managed in the Hue app; the CLI only displays them."""
    scripts = {
        s["id"]: s.get("metadata", {}).get("name", "?")
        for s in bridge.get("behavior_script")
    }
    rows = []
    for bi in bridge.get("behavior_instance"):
        kind = scripts.get(bi.get("script_id"), "?")
        if kind in _NON_AUTOMATION_SCRIPTS:
            continue
        name = bi.get("metadata", {}).get("name", "?")
        status = "on " if bi.get("enabled") else "off"
        when = ""
        we = bi.get("configuration", {}).get("when_extended")
        if we:
            start = _fmt_clock(we.get("start_at", {}))
            end = we.get("end_at")
            t = f"{start}–{_fmt_clock(end)}" if end else start
            when = f"{t}, {_fmt_days(we.get('recurrence_days', []))}"
        rows.append((status, name, kind, when))
    if not rows:
        click.echo("No automations.")
        return
    for status, name, kind, when in sorted(rows, key=lambda r: r[1].lower()):
        line = f"[{status}]  {name:<20}  {kind:<16}"
        if when:
            line += f"  {when}"
        click.echo(line)


def _list_schedules(bridge: HueBridge) -> None:
    schedules = bridge.list_schedules()
    if not schedules:
        click.echo("No schedules.")
        return
    for sid, info in sorted(schedules.items()):
        status = info.get("status", "?")
        when = describe_localtime(info.get("localtime", ""))
        name = info.get("name", "")
        click.echo(f"{sid:>3}  [{status}]  {when}  — {name}")


_LISTERS = {
    "lights": _list_lights,
    "rooms": _list_rooms,
    "scenes": _list_scenes,
    "schedules": _list_schedules,
}

# Friendly aliases -> canonical kind (singular forms, common synonyms).
_KIND_ALIASES = {
    "light": "lights",
    "room": "rooms",
    "zone": "rooms",
    "zones": "rooms",
    "scene": "scenes",
    "schedule": "schedules",
}


def _resolve_choice(value: str, canonical: dict, aliases: dict, label: str) -> str:
    """Map user input to a known choice, tolerating case, singular forms, and
    small typos. Prompts 'Did you mean X?' on a near miss, else exits."""
    key = value.strip().lower()
    if key in canonical:
        return key
    if key in aliases:
        return aliases[key]
    match = get_close_matches(key, list(canonical) + list(aliases), n=1, cutoff=0.5)
    options = ", ".join(canonical)
    if match:
        suggestion = aliases.get(match[0], match[0])
        if click.confirm(f"Did you mean '{suggestion}'?", default=True):
            return suggestion
        _fail(f"unknown {label} {value!r}  (choices: {options})")
    _fail(f"unknown {label} {value!r}  (choices: {options})")


@cli.command(name="list", short_help="List lights, rooms, scenes, or schedules.")
@click.argument("kind", required=False)
@click.argument("name", required=False)
def list_cmd(kind: str | None, name: str | None) -> None:
    """List objects on the Bridge, optionally drilling into one by name.

    \b
    Examples:
      hue list rooms                 all rooms and zones
      hue list room ThomasRoom       the lights in a room
      hue list light AllisonLight-1  one light's state
      hue list scenes ThomasRoom     the scenes in a room
    """
    if not kind:
        click.echo("Usage: hue list <type> [name]")
        click.echo(f"Types: {', '.join(_LISTERS)}")
        return
    canonical = _resolve_choice(kind, _LISTERS, _KIND_ALIASES, "type")
    bridge = _connect()
    try:
        if name:
            if canonical == "rooms":
                if not _echo_target_lights(bridge, "room", name, header="Lights in"):
                    _fail(f"no room or zone named {name!r}")
            elif canonical == "lights":
                if not _echo_target_lights(bridge, "light", name, header="Light"):
                    _fail(f"no light named {name!r}")
            elif canonical == "scenes":
                _echo_scenes_in_room(bridge, name)
            else:
                _fail(f"`hue list {canonical} <name>` isn't supported — try `hue list {canonical}`")
            return
        _LISTERS[canonical](bridge)
    except (requests.RequestException, HueError) as exc:
        _fail(str(exc))


# Named white presets (Kelvin) usable as a state, e.g. `change room X warm`.
_CT_PRESETS = {"warm": 2700, "cool": 5000}


def _state_body(state: str | None, kelvin: int | None) -> dict:
    """Build a light/group state from a ``state`` token (``on``/``off``/``warm``/
    ``cool``/0-100 brightness) and/or a color temperature. Raises ValueError on
    bad input."""
    body: dict = {}
    if state is not None:
        s = state.strip().lower()
        if s == "on":
            body["on"] = {"on": True}
        elif s == "off":
            body["on"] = {"on": False}
        elif s in _CT_PRESETS:
            body["on"] = {"on": True}
            body["color_temperature"] = {"mirek": kelvin_to_mirek(_CT_PRESETS[s])}
        else:
            try:
                level = int(s)
            except ValueError:
                raise ValueError(f"state must be on, off, warm, cool, or 0-100 (got {state!r})")
            if not 0 <= level <= 100:
                raise ValueError("brightness must be 0-100")
            if level == 0:
                body["on"] = {"on": False}
            else:
                body["on"] = {"on": True}
                body["dimming"] = {"brightness": float(level)}
    if kelvin is not None:
        body.setdefault("on", {"on": True})
        body["color_temperature"] = {"mirek": kelvin_to_mirek(kelvin)}
    if not body:
        raise ValueError("nothing to change — give a state (on/off/warm/cool/0-100)")
    return body


@cli.command(short_help="Rename a light or room.")
@click.argument("current", required=False)
@click.argument("new_name", required=False)
def rename(current: str | None, new_name: str | None) -> None:
    """Rename a light, room, or zone:  hue rename "Thomas Big 1" "Thomas 4"."""
    if not current or not new_name:
        click.echo('Usage: hue rename "<current name>" "<new name>"')
        click.echo("\nExamples:")
        click.echo('  hue rename "Thomas 1" "ThomasLight-1"   rename a light')
        click.echo('  hue rename "Living Room" "LivingRoom"   rename a room')
        bridge = _connect()
        try:
            click.echo("\nLights:")
            _list_lights(bridge)
            click.echo("\nRooms:")
            _list_rooms(bridge)
        except (requests.RequestException, HueError):
            pass
        return
    bridge = _connect()
    try:
        bridge.rename(current, new_name)
    except (requests.RequestException, HueError) as exc:
        _fail(str(exc))
    click.echo(f"renamed {current!r} -> {new_name!r}")


_CHANGE_KINDS = {"light": "light", "room": "room", "scene": "scene"}
_CHANGE_ALIASES = {
    "lights": "light",
    "bulb": "light",
    "bulbs": "light",
    "rooms": "room",
    "zone": "room",
    "zones": "room",
    "scenes": "scene",
}


@cli.command(name="change")
@click.argument("kind", required=False)
@click.argument("name", required=False)
@click.argument("state", required=False)
@click.option("--room", help="For scenes: which room's copy to activate.")
@click.option("--ct", "kelvin", type=click.IntRange(2000, 6500), help="Set color temperature (Kelvin).")
def change(kind, name, state, room, kelvin) -> None:
    """Change a light, room, or scene.

    \b
    Examples:
      hue change light "Thomas 1" off
      hue change room LivingRoom 40
      hue change room AllisonRoom warm
      hue change scene LivingRoom Bright
    """
    if not kind:
        click.echo("Usage: hue change <type> <name> [state]")
        click.echo(f"Types: {', '.join(_CHANGE_KINDS)}")
        click.echo("  light/room state: on | off | 0-100 | warm | cool")
        click.echo("  scene: hue change scene <room> <name>")
        click.echo("\nExamples:")
        click.echo("  hue change room ThomasRoom on         turn a room on")
        click.echo("  hue change room ThomasRoom off        turn a room off")
        click.echo("  hue change room ThomasRoom 50         set a room to 50% brightness")
        click.echo("  hue change room ThomasRoom warm       warm white")
        click.echo("  hue change room ThomasRoom cool       cool white")
        click.echo("  hue change scene ThomasRoom Bright    activate a scene in a room")
        return
    canonical = _resolve_choice(kind, _CHANGE_KINDS, _CHANGE_ALIASES, "type")
    if not name:
        # Show usage for this type and the available names to pick from.
        if canonical == "scene":
            click.echo("Usage: hue change scene <room> <name>   (or: <name> --room <room>)")
        else:
            click.echo(f"Usage: hue change {canonical} <name> on|off|0-100|warm|cool")
        bridge = _connect()
        click.echo(f"\nAvailable {canonical}s:")
        try:
            {"light": _list_lights, "room": _list_rooms, "scene": _list_scenes}[canonical](bridge)
        except (requests.RequestException, HueError):
            pass
        return

    # Target given but no state — guide the user instead of erroring.
    if canonical != "scene" and state is None and kelvin is None:
        disp = f'"{name}"' if " " in name else name
        click.echo(f"Usage: hue change {canonical} {disp} <state>")
        click.echo("  state: on | off | 0-100 | warm | cool")
        click.echo("\nExamples:")
        click.echo(f"  hue change {canonical} {disp} on")
        click.echo(f"  hue change {canonical} {disp} 50")
        click.echo(f"  hue change {canonical} {disp} warm")
        bridge = _connect()
        lights = _echo_target_lights(bridge, canonical, name)
        if lights and not any("color_temperature" in l for l in lights):
            click.echo("\nNote: these bulbs are white-only — warm/cool not supported.")
        return

    bridge = _connect()
    try:
        if canonical == "scene":
            # Two forms: `scene <room> <name>` (positional) or `scene <name> --room <room>`.
            scene_name, scene_room = (state, name) if state is not None else (name, room)
            bridge.activate_scene(scene_name, scene_room)
            where = f" in {scene_room}" if scene_room else ""
            click.echo(f"activated scene {scene_name!r}{where}")
            if scene_room:
                time.sleep(0.4)  # let the Bridge settle before reading back
                _echo_target_lights(bridge, "room", scene_room, header="Now in")
        else:
            body = _state_body(state, kelvin)
            bridge.set_state(name, body)
            if "color_temperature" in body and not bridge.color_temp_capable(name):
                click.echo(
                    f"{name!r}: bulbs are white-only (soft warm white) — "
                    "warm/cool not supported."
                )
            else:
                click.echo(f"changed {name!r}")
            # Show the resulting status (after a short settle for accuracy).
            time.sleep(0.4)
            _echo_target_lights(bridge, canonical, name, header="Now")
    except ValueError as exc:
        _fail(str(exc))
    except (requests.RequestException, HueError) as exc:
        _fail(str(exc))


@cli.command(name="automation", short_help="CLIP v2 — list only (Hue app automations).")
def automation() -> None:
    """List the automations managed in the Hue app (motion, schedules, button,
    wake/sleep routines). These use the modern CLIP v2 system and are read-only
    here — create and edit them in the Hue app. Schedules created with
    `hue schedule` are a separate, CLI-only mechanism."""
    bridge = _connect()
    try:
        _list_automations(bridge)
    except (requests.RequestException, HueError) as exc:
        _fail(str(exc))


@cli.group(invoke_without_command=True, short_help="CLIP v1 — add / delete / list (CLI schedules).")
@click.pass_context
def schedule(ctx: click.Context) -> None:
    """Manage CLI schedules — time rules created by this tool that run on the
    Bridge (fire even when this Mac is off). These are separate from the Hue
    app's automations; see `hue automation` for those."""
    if ctx.invoked_subcommand is None:
        bridge = _connect()
        try:
            _list_schedules(bridge)
        except (requests.RequestException, HueError) as exc:
            _fail(str(exc))
        click.echo("\nUsage: hue schedule add <target> on|off [--at TIME] [--days ...] [--dim N]")
        click.echo("       hue schedule delete <id>")
        click.echo("       (--at accepts 11pm or 23:00)")
        click.echo("\nExamples:")
        click.echo("  hue schedule add ThomasRoom off --at 11pm               daily at 11pm")
        click.echo("  hue schedule add ThomasRoom on --at 7am --days weekdays")
        click.echo("  hue schedule add ThomasRoom on --at 7am --dim 60        dim to 60%")
        click.echo("  hue schedule add ThomasRoom off --in 30                 timer: 30 min")
        click.echo("  hue schedule add ThomasRoom off --at 10:30pm --date 2026-07-04   one-time")
        click.echo("\nNote: these are CLI-only and won't show in the Hue app.")
        click.echo("      For the app's automations, run:  hue automation")


@schedule.command(name="add")
@click.argument("target")
@click.argument("action", type=click.Choice(["on", "off"]))
@click.option("--at", "at_time", help="Time of day: 11pm or 23:00. For daily/weekday/one-time triggers.")
@click.option("--days", default="everyday", show_default=True,
              help="everyday | weekdays | weekend | comma list e.g. mon,wed,fri")
@click.option("--date", "on_date", help="One-time trigger on YYYY-MM-DD (with --at).")
@click.option("--in", "in_minutes", type=int, help="Timer: fire once after N minutes.")
@click.option("--dim", type=click.IntRange(1, 100), help="Brightness 1-100 when action is 'on'.")
@click.option("--name", "sched_name", help="Schedule name (defaults to a generated one).")
def schedule_add(target, action, at_time, days, on_date, in_minutes, dim, sched_name):
    """Create a Bridge schedule.

    Examples:
      hue schedule add Livingroom off --at 11pm
      hue schedule add "Allison Bedroom" on --at 7am --days weekdays --dim 60
      hue schedule add Livingroom off --in 30
      hue schedule add Downstairs off --at 10:30pm --date 2026-07-04
    """
    turn_on = action == "on"
    if in_minutes is None and not at_time:
        _fail("provide --at TIME (or --in MINUTES for a timer)")

    try:
        localtime = build_localtime(at_time or "00:00", days=days, date=on_date, timer_minutes=in_minutes)
        body = action_body(turn_on, dim)
    except ValueError as exc:
        _fail(str(exc))

    name = sched_name or f"hue-cli {target} {action}"

    bridge = _connect()
    try:
        sid = bridge.add_schedule(name, target, localtime, body)
    except (requests.RequestException, HueError) as exc:
        _fail(str(exc))
    click.echo(f"created schedule {sid}: {name}  [{describe_localtime(localtime)}]")


@schedule.command(name="list")
def schedule_list():
    """List schedules stored on the Bridge (same as `hue list schedules`)."""
    bridge = _connect()
    try:
        _list_schedules(bridge)
    except (requests.RequestException, HueError) as exc:
        _fail(str(exc))


@schedule.command(name="delete")
@click.argument("schedule_id")
def schedule_delete(schedule_id):
    """Delete a schedule by id (see `hue schedule list`)."""
    bridge = _connect()
    try:
        bridge.delete_schedule(schedule_id)
    except (requests.RequestException, HueError) as exc:
        _fail(str(exc))
    click.echo(f"deleted schedule {schedule_id}")


def main() -> None:
    """Entry point: run the CLI, then always print a trailing blank line so
    every `hue` invocation ends with a blank line before the prompt."""
    try:
        cli.main(standalone_mode=True)
    finally:
        # Trailing blank line; if stdout is already closed (e.g. piped into
        # `head`, which closes the pipe early) redirect it to devnull so the
        # interpreter's shutdown flush doesn't print a BrokenPipeError.
        try:
            click.echo()
            sys.stdout.flush()
        except (BrokenPipeError, OSError, ValueError):
            try:
                os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
            except OSError:
                pass


if __name__ == "__main__":
    main()
