from __future__ import annotations

from datetime import datetime
from pathlib import Path

from simulated_assets.config import AssetConfig, BatteryConfig, GridMeterConfig, load_asset_configs
from simulated_assets.domain import (
    ActionResult,
    ApplyPowerAction,
    AssetSimulator,
    GridMeterObservationResult,
    ObservationResult,
    ResetResult,
    ResetSocAction,
)
from simulated_assets.errors import AssetNotFoundError
from simulated_assets.simulators import BatterySimulator, GridMeterSimulator


class AssetRegistry:
    def __init__(self, simulators: dict[str, AssetSimulator]) -> None:
        if not simulators:
            raise ValueError("AssetRegistry requires at least one simulator")
        self._simulators = simulators

    @classmethod
    def from_config_file(cls, config_path: Path, start_time: datetime) -> "AssetRegistry":
        configs = load_asset_configs(config_path)
        return cls.from_configs(configs, start_time=start_time)

    @classmethod
    def from_configs(
        cls,
        configs: list[AssetConfig],
        start_time: datetime,
    ) -> "AssetRegistry":
        simulators: dict[str, AssetSimulator] = {}
        for config in configs:
            if config.asset_id in simulators:
                raise ValueError(f"Duplicate asset_id found: {config.asset_id}")

            if isinstance(config, BatteryConfig):
                simulators[config.asset_id] = BatterySimulator(config, start_time=start_time)
                continue

            if isinstance(config, GridMeterConfig):
                simulators[config.asset_id] = GridMeterSimulator(config, start_time=start_time)
                continue

            raise ValueError(f"Unsupported asset config: {type(config).__name__}")

        return cls(simulators)

    def apply_action(
        self,
        asset_id: str,
        now: datetime,
        action: ApplyPowerAction,
    ) -> ActionResult:
        simulator = self._simulators.get(asset_id)
        if simulator is None:
            raise AssetNotFoundError(asset_id)
        return simulator.apply_action(now=now, action=action)

    def get_observation(
        self,
        asset_id: str,
        now: datetime,
        window_seconds: int | None,
    ) -> ObservationResult | GridMeterObservationResult:
        simulator = self._simulators.get(asset_id)
        if simulator is None:
            raise AssetNotFoundError(asset_id)
        return simulator.get_observation(now=now, window_seconds=window_seconds)

    def reset_soc(
        self,
        asset_id: str,
        now: datetime,
        action: ResetSocAction,
    ) -> ResetResult:
        simulator = self._simulators.get(asset_id)
        if simulator is None:
            raise AssetNotFoundError(asset_id)
        return simulator.reset_soc(now=now, action=action)
