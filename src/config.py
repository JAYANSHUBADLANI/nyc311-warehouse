"""Loads config/config.yml and resolves paths relative to the repo root.

Every script and every dbt run reads its date window, agency filter, SLA target
and vintage cadence from here. Nothing downstream should carry its own copy of
those values.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "config.yml"


class Config:
    def __init__(self, raw: dict[str, Any], repo_root: Path):
        self._raw = raw
        self.repo_root = repo_root

    def __getitem__(self, key: str) -> Any:
        return self._raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._raw.get(key, default)

    @property
    def raw(self) -> dict[str, Any]:
        return self._raw

    def path(self, key: str) -> Path:
        """Resolve one of the entries under paths: to an absolute path."""
        return self.repo_root / self._raw["paths"][key]

    @property
    def app_token(self) -> str | None:
        """Socrata app token, or None to run on the throttled anonymous tier.

        Read from the environment only. A token must never be committed.
        """
        var = self._raw["socrata"]["app_token_env_var"]
        token = os.environ.get(var)
        return token if token else None


def load_config(path: Path | None = None) -> Config:
    path = path or CONFIG_PATH
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    return Config(raw, path.resolve().parent.parent)
