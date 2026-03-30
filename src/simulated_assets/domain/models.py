from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ApplyPowerAction:
    power_kw: float


@dataclass(frozen=True)
class ResetSocAction:
    soc_pct: float


@dataclass(frozen=True)
class ActionResult:
    requested_power_kw: float
    applied_power_kw: float
    was_saturated: bool
    saturation_reasons: list[str]
    soc_pct: float
    stored_energy_kwh: float
    timestamp: datetime


@dataclass(frozen=True)
class ObservationResult:
    instantaneous_power_kw: float
    mode: str
    soc_pct: float
    stored_energy_kwh: float
    window_seconds_requested: int
    window_seconds_effective: int
    energy_charged_kwh_window: float
    energy_discharged_kwh_window: float
    net_energy_kwh_window: float
    timestamp: datetime


@dataclass(frozen=True)
class GridMeterObservationResult:
    energy_in_total: float
    energy_in_l1: float | None
    energy_in_l2: float | None
    energy_in_l3: float | None
    energy_out_total: float
    energy_out_l1: float | None
    energy_out_l2: float | None
    energy_out_l3: float | None


@dataclass(frozen=True)
class ResetResult:
    requested_soc_pct: float
    soc_pct: float
    stored_energy_kwh: float
    applied_power_kw: float
    timestamp: datetime


class AssetSimulator(ABC):
    @abstractmethod
    def apply_action(self, now: datetime, action: ApplyPowerAction) -> ActionResult:
        """Apply an action to the simulator and return the updated state snapshot."""

    @abstractmethod
    def get_observation(
        self,
        now: datetime,
        window_seconds: int | None,
    ) -> ObservationResult | GridMeterObservationResult:
        """Return an observation snapshot for the requested window."""

    @abstractmethod
    def reset_soc(self, now: datetime, action: ResetSocAction) -> ResetResult:
        """Reset asset state to a requested SOC and return updated snapshot."""
