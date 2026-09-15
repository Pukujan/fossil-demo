from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    db_path: Path
    workspace_root: Path
    workspace_ttl_seconds: int = 24 * 60 * 60
    cookie_secure: bool = True
