"""Persistence of the Bridge connection details (IP + application key).

Config lives at ~/.config/hue/config.json (override with $HUE_CONFIG):

    {
        "bridge_ip": "192.168.1.42",
        "app_key": "abcd1234...",
        "client_key": "..."   # optional, only needed for the Entertainment API
    }
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


def config_path() -> Path:
    override = os.environ.get("HUE_CONFIG")
    if override:
        return Path(override)
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "hue" / "config.json"


@dataclass
class Config:
    bridge_ip: Optional[str] = None
    app_key: Optional[str] = None
    client_key: Optional[str] = None

    @property
    def is_paired(self) -> bool:
        return bool(self.bridge_ip and self.app_key)

    @classmethod
    def load(cls) -> "Config":
        path = config_path()
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        return cls(
            bridge_ip=data.get("bridge_ip"),
            app_key=data.get("app_key"),
            client_key=data.get("client_key"),
        )

    def save(self) -> Path:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")
        # The app key is a credential — keep it owner-readable only.
        path.chmod(0o600)
        return path
