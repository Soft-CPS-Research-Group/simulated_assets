from __future__ import annotations

from datetime import datetime
from pathlib import Path

from simulated_assets.config import BatteryConfig, load_battery_configs
from simulated_assets.domain import ActionResult, ApplyPowerAction, AssetSimulator, ObservationResult
from simulated_assets.errors import AssetNotFoundError
from simulated_assets.simulators import BatterySimulator


class AssetRegistry:
    def __init__(self, simulators: dict[str, AssetSimulator]) -> None:
        if not simulators:
            raise ValueError("AssetRegistry requires at least one simulator")
        self._simulators = simulators

    @classmethod
    def from_config_file(cls, config_path: Path, start_time: datetime) -> "AssetRegistry":
        configs = load_battery_configs(config_path)
        return cls.from_configs(configs, start_time=start_time)

    @classmethod
    def from_configs(
        cls,
        configs: list[BatteryConfig],
        start_time: datetime,
    ) -> "AssetRegistry":
        simulators: dict[str, AssetSimulator] = {}
        for config in configs:
            if config.asset_id in simulators:
                raise ValueError(f"Duplicate asset_id found: {config.asset_id}")

            if config.asset_type == "home_battery":
                simulators[config.asset_id] = BatterySimulator(config, start_time=start_time)
            else:
                raise ValueError(f"Unsupported asset_type: {config.asset_type}")

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
    ) -> ObservationResult:
        simulator = self._simulators.get(asset_id)
        if simulator is None:
            raise AssetNotFoundError(asset_id)
        return simulator.get_observation(now=now, window_seconds=window_seconds)
