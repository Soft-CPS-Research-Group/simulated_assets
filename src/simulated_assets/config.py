from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class BatteryConfig(BaseModel):
    asset_id: str = Field(min_length=1)
    asset_type: Literal["home_battery"] = "home_battery"
    capacity_kwh: float = Field(gt=0)
    initial_soc_pct: float = Field(ge=0, le=100)
    soc_min_pct: float = Field(ge=0, le=100)
    soc_max_pct: float = Field(ge=0, le=100)
    max_charge_power_kw: float = Field(gt=0)
    min_charge_power_kw: float = Field(ge=0)
    min_discharge_power_kw: float = Field(ge=0)
    max_discharge_power_kw: float = Field(gt=0)
    efficiency: float = Field(gt=0, le=1)
    default_observation_window_seconds: int = Field(gt=0)
    max_observation_window_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> "BatteryConfig":
        if self.soc_min_pct >= self.soc_max_pct:
            raise ValueError("soc_min_pct must be less than soc_max_pct")
        if not (self.soc_min_pct <= self.initial_soc_pct <= self.soc_max_pct):
            raise ValueError("initial_soc_pct must be inside [soc_min_pct, soc_max_pct]")
        if self.min_charge_power_kw > self.max_charge_power_kw:
            raise ValueError("min_charge_power_kw must be <= max_charge_power_kw")
        if self.min_discharge_power_kw > self.max_discharge_power_kw:
            raise ValueError("min_discharge_power_kw must be <= max_discharge_power_kw")
        if self.default_observation_window_seconds > self.max_observation_window_seconds:
            raise ValueError(
                "default_observation_window_seconds must be <= max_observation_window_seconds"
            )
        return self


class GridMeterConfig(BaseModel):
    asset_id: str = Field(min_length=1)
    asset_type: Literal["grid_meter"] = "grid_meter"
    default_observation_window_seconds: int = Field(gt=0)
    max_observation_window_seconds: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> "GridMeterConfig":
        if self.default_observation_window_seconds > self.max_observation_window_seconds:
            raise ValueError(
                "default_observation_window_seconds must be <= max_observation_window_seconds"
            )
        return self


AssetConfig = BatteryConfig | GridMeterConfig


class AssetsFile(BaseModel):
    assets: list[dict]


def _parse_asset_config(item: dict) -> AssetConfig:
    asset_type = item.get("asset_type", "home_battery")
    if asset_type == "home_battery":
        return BatteryConfig.model_validate(item)
    if asset_type == "grid_meter":
        return GridMeterConfig.model_validate(item)
    raise ValueError(f"Unsupported asset_type: {asset_type}")


def load_asset_configs(config_path: Path) -> list[AssetConfig]:
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        configs = [_parse_asset_config(item) for item in raw]
    else:
        assets_file = AssetsFile.model_validate(raw)
        configs = [_parse_asset_config(item) for item in assets_file.assets]

    if not configs:
        raise ValueError("At least one asset config is required")

    return configs


def load_battery_configs(config_path: Path) -> list[BatteryConfig]:
    configs = load_asset_configs(config_path)
    batteries = [config for config in configs if isinstance(config, BatteryConfig)]
    if not batteries:
        raise ValueError("At least one battery asset config is required")
    return batteries
