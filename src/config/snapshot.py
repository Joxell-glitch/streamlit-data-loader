from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict

from src.config.models import Settings


def safe_config_snapshot(settings: Settings) -> Dict[str, Any]:
    if is_dataclass(settings):
        return asdict(settings)
    if hasattr(settings, "dict"):
        return settings.dict()
    return dict(settings)
