"""Load and validate config-driven universe definitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_DEFINITIONS_PATH = Path("data/config/universe_definitions.yaml")
REQUIRED_UNIVERSE_FIELDS = {
    "description",
    "benchmark_family",
    "intended_use",
    "min_price",
    "min_adv_20d",
    "min_adv_60d",
    "include_asset_types",
    "exclude_asset_types",
    "refresh_frequency",
}


@dataclass(frozen=True)
class UniverseDefinition:
    name: str
    description: str
    benchmark_family: str
    intended_use: str
    min_price: float
    min_adv_20d: float
    min_adv_60d: float
    include_asset_types: tuple[str, ...]
    exclude_asset_types: tuple[str, ...]
    refresh_frequency: str
    min_market_cap: float | None = None
    max_market_cap: float | None = None

    @classmethod
    def from_mapping(cls, name: str, data: dict[str, Any]) -> "UniverseDefinition":
        missing = REQUIRED_UNIVERSE_FIELDS - set(data)
        if missing:
            raise ValueError(f"{name} missing required universe definition fields: {sorted(missing)}")
        include = _asset_type_tuple(data["include_asset_types"], f"{name}.include_asset_types")
        exclude = _asset_type_tuple(data["exclude_asset_types"], f"{name}.exclude_asset_types")
        min_price = _non_negative_float(data["min_price"], f"{name}.min_price")
        min_adv_20d = _non_negative_float(data["min_adv_20d"], f"{name}.min_adv_20d")
        min_adv_60d = _non_negative_float(data["min_adv_60d"], f"{name}.min_adv_60d")
        min_market_cap = _optional_non_negative_float(data.get("min_market_cap"), f"{name}.min_market_cap")
        max_market_cap = _optional_non_negative_float(data.get("max_market_cap"), f"{name}.max_market_cap")
        if min_market_cap is not None and max_market_cap is not None and min_market_cap > max_market_cap:
            raise ValueError(f"{name} min_market_cap cannot exceed max_market_cap")
        return cls(
            name=name,
            description=str(data["description"]),
            benchmark_family=str(data["benchmark_family"]),
            intended_use=str(data["intended_use"]),
            min_price=min_price,
            min_adv_20d=min_adv_20d,
            min_adv_60d=min_adv_60d,
            include_asset_types=include,
            exclude_asset_types=exclude,
            refresh_frequency=str(data["refresh_frequency"]),
            min_market_cap=min_market_cap,
            max_market_cap=max_market_cap,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "benchmark_family": self.benchmark_family,
            "intended_use": self.intended_use,
            "min_price": self.min_price,
            "min_adv_20d": self.min_adv_20d,
            "min_adv_60d": self.min_adv_60d,
            "min_market_cap": self.min_market_cap,
            "max_market_cap": self.max_market_cap,
            "include_asset_types": list(self.include_asset_types),
            "exclude_asset_types": list(self.exclude_asset_types),
            "refresh_frequency": self.refresh_frequency,
        }


@dataclass(frozen=True)
class UniverseConfig:
    global_settings: dict[str, Any]
    definitions: dict[str, UniverseDefinition]

    def to_dict(self) -> dict[str, Any]:
        return {
            "global_settings": self.global_settings,
            "universes": {name: definition.to_dict() for name, definition in self.definitions.items()},
        }


def load_universe_config(path: str | Path = DEFAULT_DEFINITIONS_PATH) -> UniverseConfig:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("universe definitions YAML must be a mapping")
    universes = payload.get("universes")
    if not isinstance(universes, dict) or not universes:
        raise ValueError("universe definitions YAML must include non-empty universes mapping")
    settings = payload.get("global_settings") or {}
    if not isinstance(settings, dict):
        raise ValueError("global_settings must be a mapping")
    definitions = {
        str(name): UniverseDefinition.from_mapping(str(name), data)
        for name, data in universes.items()
        if _ensure_mapping(data, str(name))
    }
    return UniverseConfig(global_settings=settings, definitions=definitions)


def _ensure_mapping(data: Any, name: str) -> bool:
    if not isinstance(data, dict):
        raise ValueError(f"{name} universe definition must be a mapping")
    return True


def _asset_type_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} must be a non-empty list")
    normalized = tuple(str(item).strip().upper() for item in value if str(item).strip())
    if len(normalized) != len(value):
        raise ValueError(f"{field_name} contains an empty asset type")
    return normalized


def _non_negative_float(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if number < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return number


def _optional_non_negative_float(value: Any, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    return _non_negative_float(value, field_name)
