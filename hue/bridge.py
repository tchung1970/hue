"""Client for the Philips Hue Bridge local CLIP v2 API.

Two phases:

  * Discovery + pairing (`discover_bridges`, `pair`) — done once during setup.
  * Control (`HueBridge`) — list and command resources using a saved app key.

Everything here is LAN-only — no Philips cloud service is ever contacted.
Discovery uses local SSDP/UPnP multicast. The Bridge serves HTTPS with a
self-signed certificate bound to its bridge-id, not its IP, so hostname
verification cannot succeed against the LAN IP; we disable verification and talk
to the Bridge directly on the local network.
"""

from __future__ import annotations

import socket
from typing import Any, Dict, List, Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Identifies this client to the Bridge; the part after '#' is informational.
DEVICE_TYPE = "hue-cli#cli"


class HueError(Exception):
    pass


class LinkButtonNotPressed(HueError):
    """Raised during pairing when the Bridge's physical link button wasn't pressed."""


_SSDP_ADDR = ("239.255.255.250", 1900)


def discover_bridges(timeout: float = 4.0) -> List[Dict[str, str]]:
    """Find Hue Bridges on the local network via SSDP/UPnP multicast.

    LAN-only — no cloud service is contacted. Returns a list of dicts with an
    ``internalipaddress`` (and ``id`` when the bridge reports it). Returns an
    empty list if none respond; the user can always pass the IP explicitly.
    """
    request = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 2\r\n"
        "ST: ssdp:all\r\n"
        "\r\n"
    ).encode()
    found: Dict[str, Dict[str, str]] = {}
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(timeout)
        try:
            sock.sendto(request, _SSDP_ADDR)
            while True:
                try:
                    data, addr = sock.recvfrom(65507)
                except socket.timeout:
                    break
                text = data.decode(errors="ignore")
                lower = text.lower()
                # Hue bridges advertise "IpBridge" in SERVER and a hue-bridgeid header.
                if "ipbridge" not in lower and "hue-bridgeid" not in lower:
                    continue
                ip = addr[0]
                bridge_id = "?"
                for line in text.split("\r\n"):
                    if line.lower().startswith("hue-bridgeid:"):
                        bridge_id = line.split(":", 1)[1].strip().lower()
                found[ip] = {"internalipaddress": ip, "id": bridge_id}
        finally:
            sock.close()
    except OSError:
        pass
    return list(found.values())


def bridge_public_config(bridge_ip: str, *, timeout: float = 5.0) -> Dict[str, Any]:
    """Fetch the Bridge's public config (name, model, firmware, API version).

    The legacy ``/api/0/config`` endpoint returns a limited subset **without**
    authentication, so this works even before pairing.
    """
    resp = requests.get(f"https://{bridge_ip}/api/0/config", verify=False, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def pair(bridge_ip: str, *, timeout: float = 5.0) -> Dict[str, str]:
    """Create an application key on the Bridge.

    The physical link button on the Bridge must be pressed within ~30s before
    calling this. Returns ``{"username": <app_key>, "clientkey": <client_key>}``.
    Raises :class:`LinkButtonNotPressed` if the button wasn't pressed.
    """
    resp = requests.post(
        f"https://{bridge_ip}/api",
        json={"devicetype": DEVICE_TYPE, "generateclientkey": True},
        verify=False,
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    # The legacy /api endpoint returns a single-element list.
    entry = payload[0] if isinstance(payload, list) else payload
    if "error" in entry:
        err = entry["error"]
        if err.get("type") == 101:
            raise LinkButtonNotPressed(err.get("description", "link button not pressed"))
        raise HueError(err.get("description", str(err)))
    return entry["success"]


class HueBridge:
    """Thin wrapper over the CLIP v2 ``/clip/v2/resource`` endpoints."""

    def __init__(self, ip: str, app_key: str, *, timeout: float = 5.0):
        self.ip = ip
        self.app_key = app_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({"hue-application-key": app_key})

    # -- low-level ---------------------------------------------------------

    def _url(self, resource: str, rid: Optional[str] = None) -> str:
        base = f"https://{self.ip}/clip/v2/resource/{resource}"
        return f"{base}/{rid}" if rid else base

    def get(self, resource: str, rid: Optional[str] = None) -> List[Dict[str, Any]]:
        resp = self.session.get(self._url(resource, rid), timeout=self.timeout)
        resp.raise_for_status()
        return resp.json().get("data", [])

    def put(self, resource: str, rid: str, body: Dict[str, Any]) -> List[Dict[str, Any]]:
        resp = self.session.put(self._url(resource, rid), json=body, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            raise HueError("; ".join(e.get("description", str(e)) for e in data["errors"]))
        return data.get("data", [])

    # -- resources ---------------------------------------------------------

    def lights(self) -> List[Dict[str, Any]]:
        return self.get("light")

    def rooms(self) -> List[Dict[str, Any]]:
        return self.get("room")

    def zones(self) -> List[Dict[str, Any]]:
        return self.get("zone")

    def grouped_lights(self) -> List[Dict[str, Any]]:
        return self.get("grouped_light")

    def scenes(self) -> List[Dict[str, Any]]:
        return self.get("scene")

    # -- name resolution ---------------------------------------------------

    def resolve_target(self, name: str) -> tuple[str, str]:
        """Resolve a light/room/zone name (case-insensitive) to a controllable
        ``(resource_type, resource_id)`` pair.

        Lights resolve to ``("light", id)``; rooms and zones resolve to their
        backing ``("grouped_light", id)`` service so the whole group is set at once.
        """
        needle = name.strip().lower()

        for light in self.lights():
            if light.get("metadata", {}).get("name", "").lower() == needle:
                return "light", light["id"]

        for group in self.rooms() + self.zones():
            if group.get("metadata", {}).get("name", "").lower() == needle:
                for service in group.get("services", []):
                    if service.get("rtype") == "grouped_light":
                        return "grouped_light", service["rid"]

        raise HueError(f"no light, room, or zone named {name!r}")

    def resolve_named_resource(self, name: str) -> tuple[str, str]:
        """Resolve a name to the underlying ``(resource_type, id)`` that owns the
        name — a ``light``, ``room``, or ``zone`` (not the ``grouped_light``
        service). Used for renaming, where the name lives on the resource itself."""
        needle = name.strip().lower()
        for rtype in ("light", "room", "zone"):
            for res in self.get(rtype):
                if res.get("metadata", {}).get("name", "").lower() == needle:
                    return rtype, res["id"]
        raise HueError(f"no light, room, or zone named {name!r}")

    def resolve_scene(self, name: str, room: Optional[str] = None) -> str:
        """Resolve a scene name to its id. Scene names repeat across rooms, so
        when more than one matches, ``room`` is required to disambiguate."""
        needle = name.strip().lower()
        group_names = {
            g["id"]: g.get("metadata", {}).get("name", "?")
            for g in self.rooms() + self.zones()
        }
        matches = [
            (s["id"], group_names.get(s.get("group", {}).get("rid"), "?"))
            for s in self.scenes()
            if s.get("metadata", {}).get("name", "").lower() == needle
        ]
        if not matches:
            raise HueError(f"no scene named {name!r}")

        if room:
            room_needle = room.strip().lower()
            for sid, room_name in matches:
                if room_name.lower() == room_needle:
                    return sid
            raise HueError(f"no scene named {name!r} in room {room!r}")

        if len(matches) == 1:
            return matches[0][0]
        rooms = ", ".join(sorted(r for _, r in matches))
        raise HueError(f"scene {name!r} exists in multiple rooms ({rooms}); pass --room")

    # -- commands ----------------------------------------------------------

    def _group_member_lights(self, name: str) -> List[Dict[str, Any]]:
        """Full light resources belonging to a room or zone (rooms group
        devices, zones group lights directly)."""
        needle = name.strip().lower()
        lights = self.lights()
        for room in self.rooms():
            if room.get("metadata", {}).get("name", "").lower() == needle:
                device_ids = {
                    c["rid"] for c in room.get("children", []) if c.get("rtype") == "device"
                }
                return [l for l in lights if l.get("owner", {}).get("rid") in device_ids]
        for zone in self.zones():
            if zone.get("metadata", {}).get("name", "").lower() == needle:
                ids = {c["rid"] for c in zone.get("children", []) if c.get("rtype") == "light"}
                return [l for l in lights if l["id"] in ids]
        return []

    def color_temp_capable(self, name: str) -> bool:
        """Whether the target (a light, or any bulb in a room/zone) supports
        color temperature. Used to warn when warm/cool would have no effect."""
        rtype, rid = self.resolve_target(name)
        if rtype == "light":
            light = self.get("light", rid)
            return bool(light) and "color_temperature" in light[0]
        return any("color_temperature" in l for l in self._group_member_lights(name))

    def set_state(self, name: str, body: Dict[str, Any]) -> None:
        rtype, rid = self.resolve_target(name)
        # grouped_light only supports on/off and dimming; color and color
        # temperature must be set on each member light individually, and only on
        # the lights that actually support those features.
        if rtype == "grouped_light" and ("color" in body or "color_temperature" in body):
            members = self._group_member_lights(name)
            if members:
                for light in members:
                    sub = dict(body)
                    if "color_temperature" not in light:
                        sub.pop("color_temperature", None)
                    if "color" not in light:
                        sub.pop("color", None)
                    if sub:
                        self.put("light", light["id"], sub)
                return
        self.put(rtype, rid, body)

    def rename(self, name: str, new_name: str) -> None:
        rtype, rid = self.resolve_named_resource(name)
        self.put(rtype, rid, {"metadata": {"name": new_name}})
        if rtype == "light":
            # The Hue app displays the *device* name, not the light name, so a
            # light rename alone is invisible in the app. Keep them in sync by
            # also renaming the device that owns this light.
            light = self.get("light", rid)
            owner = light[0].get("owner", {}) if light else {}
            if owner.get("rtype") == "device":
                self.put("device", owner["rid"], {"metadata": {"name": new_name}})

    def activate_scene(self, name: str, room: Optional[str] = None) -> None:
        rid = self.resolve_scene(name, room)
        self.put("scene", rid, {"recall": {"action": "active"}})

    # -- schedules (CLIP v1) ----------------------------------------------
    #
    # The CLIP v2 API has no general-purpose scheduler; the Bridge's built-in
    # scheduler lives on the legacy /api/<key>/... v1 endpoints, which still run
    # on current firmware. The app key doubles as the v1 username.

    def _v1_url(self, path: str) -> str:
        return f"https://{self.ip}/api/{self.app_key}/{path}"

    def _v1(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        resp = self.session.request(method, self._v1_url(path), json=body, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        # v1 reports failures as a list of {"error": {...}} objects.
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "error" in item:
                    raise HueError(item["error"].get("description", str(item["error"])))
        return data

    def resolve_v1_target(self, name: str) -> str:
        """Resolve a light/room/zone name to the v1 command *address* a schedule
        will act on (e.g. ``groups/3/action`` or ``lights/5/state``)."""
        needle = name.strip().lower()
        if needle in ("all", "all lights"):
            return "groups/0/action"  # group 0 is the special "all lights" group
        for lid, info in self._v1("GET", "lights").items():
            if info.get("name", "").lower() == needle:
                return f"lights/{lid}/state"
        for gid, info in self._v1("GET", "groups").items():
            if info.get("name", "").lower() == needle:
                return f"groups/{gid}/action"
        raise HueError(f"no light, room, or zone named {name!r}")

    def add_schedule(
        self,
        name: str,
        target: str,
        localtime: str,
        action: Dict[str, Any],
    ) -> str:
        address = self.resolve_v1_target(target)
        # Note: we deliberately omit `autodelete` — recent Bridge firmware
        # rejects it ("parameter not available"). The Bridge applies its own
        # default (one-time/timer schedules still self-delete after firing).
        body = {
            "name": name,
            "localtime": localtime,
            "command": {
                "address": f"/api/{self.app_key}/{address}",
                "method": "PUT",
                "body": action,
            },
            "status": "enabled",
            "recycle": False,
        }
        result = self._v1("POST", "schedules", body)
        return result[0]["success"]["id"]

    def list_schedules(self) -> Dict[str, Any]:
        return self._v1("GET", "schedules")

    def delete_schedule(self, schedule_id: str) -> None:
        self._v1("DELETE", f"schedules/{schedule_id}")
