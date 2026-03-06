from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isclose

from simulated_assets.config import BatteryConfig
from simulated_assets.domain import (
    ActionResult,
    ApplyPowerAction,
    AssetSimulator,
    ObservationResult,
)
from simulated_assets.errors import InvalidWindowError

EPSILON = 1e-9


@dataclass
class PowerSegment:
    start: datetime
    end: datetime
    power_kw: float


class BatterySimulator(AssetSimulator):
    def __init__(self, config: BatteryConfig, start_time: datetime) -> None:
        self._config = config
        self._started_at = self._ensure_aware(start_time)
        self._last_update_ts = self._started_at

        self._energy_min_kwh = self._config.capacity_kwh * self._config.soc_min_pct / 100.0
        self._energy_max_kwh = self._config.capacity_kwh * self._config.soc_max_pct / 100.0

        self._stored_energy_kwh = (
            self._config.capacity_kwh * self._config.initial_soc_pct / 100.0
        )
        self._soc_pct = self._config.initial_soc_pct

        self._current_setpoint_kw = 0.0
        self._current_applied_power_kw = 0.0
        self._history: list[PowerSegment] = []

    def apply_action(self, now: datetime, action: ApplyPowerAction) -> ActionResult:
        now = self._ensure_aware(now)
        self._advance_to(now)

        requested_power = action.power_kw
        reasons: list[str] = []

        setpoint_power = self._sanitize_requested_power(requested_power, reasons)
        applied_power = self._clamp_by_soc_boundaries(setpoint_power, reasons)

        self._current_setpoint_kw = setpoint_power
        self._current_applied_power_kw = applied_power

        was_saturated = (not isclose(requested_power, applied_power, abs_tol=EPSILON)) or bool(
            reasons
        )

        return ActionResult(
            requested_power_kw=requested_power,
            applied_power_kw=applied_power,
            was_saturated=was_saturated,
            saturation_reasons=reasons,
            soc_pct=self._soc_pct,
            stored_energy_kwh=self._stored_energy_kwh,
            timestamp=now,
        )

    def get_observation(
        self,
        now: datetime,
        window_seconds: int | None,
    ) -> ObservationResult:
        now = self._ensure_aware(now)
        self._advance_to(now)

        resolved_window = self._resolve_window_seconds(window_seconds)
        charged_kwh, discharged_kwh = self._window_energies(now, resolved_window)

        uptime_seconds = max(0, int((now - self._started_at).total_seconds()))
        effective_window = min(resolved_window, uptime_seconds)

        return ObservationResult(
            instantaneous_power_kw=self._current_applied_power_kw,
            mode=self._mode_for_power(self._current_applied_power_kw),
            soc_pct=self._soc_pct,
            stored_energy_kwh=self._stored_energy_kwh,
            window_seconds_requested=resolved_window,
            window_seconds_effective=effective_window,
            energy_charged_kwh_window=charged_kwh,
            energy_discharged_kwh_window=discharged_kwh,
            net_energy_kwh_window=charged_kwh - discharged_kwh,
            timestamp=now,
        )

    def _resolve_window_seconds(self, window_seconds: int | None) -> int:
        if window_seconds is None:
            return self._config.default_observation_window_seconds
        if window_seconds < 1 or window_seconds > self._config.max_observation_window_seconds:
            raise InvalidWindowError(window_seconds, self._config.max_observation_window_seconds)
        return window_seconds

    def _sanitize_requested_power(self, requested_power: float, reasons: list[str]) -> float:
        if requested_power > 0:
            if requested_power < self._config.min_charge_power_kw:
                self._append_reason(reasons, "below_min_charge_power_deadband")
                return 0.0
            if requested_power > self._config.max_charge_power_kw:
                self._append_reason(reasons, "clamped_to_max_charge_power")
                return self._config.max_charge_power_kw
            return requested_power

        if requested_power < 0:
            discharge_power = abs(requested_power)
            if discharge_power < self._config.min_discharge_power_kw:
                self._append_reason(reasons, "below_min_discharge_power_deadband")
                return 0.0
            if discharge_power > self._config.max_discharge_power_kw:
                self._append_reason(reasons, "clamped_to_max_discharge_power")
                return -self._config.max_discharge_power_kw
            return requested_power

        return 0.0

    def _clamp_by_soc_boundaries(self, power_kw: float, reasons: list[str]) -> float:
        if power_kw > 0 and self._stored_energy_kwh >= self._energy_max_kwh - EPSILON:
            self._append_reason(reasons, "soc_max_reached")
            return 0.0

        if power_kw < 0 and self._stored_energy_kwh <= self._energy_min_kwh + EPSILON:
            self._append_reason(reasons, "soc_min_reached")
            return 0.0

        return power_kw

    def _advance_to(self, now: datetime) -> None:
        now = self._ensure_aware(now)

        if now <= self._last_update_ts:
            return

        interval_start = self._last_update_ts
        interval_end = now
        applied_power = self._current_applied_power_kw

        if isclose(applied_power, 0.0, abs_tol=EPSILON):
            self._last_update_ts = now
            self._prune_history(now)
            return

        interval_seconds = (interval_end - interval_start).total_seconds()

        if applied_power > 0:
            available_headroom = self._energy_max_kwh - self._stored_energy_kwh
            if available_headroom <= EPSILON:
                self._current_applied_power_kw = 0.0
                self._last_update_ts = now
                self._prune_history(now)
                return

            charge_rate_kwh_per_hour = applied_power * self._config.efficiency
            time_to_limit_seconds = available_headroom / charge_rate_kwh_per_hour * 3600.0

            if time_to_limit_seconds >= interval_seconds - EPSILON:
                self._apply_segment(interval_start, interval_end, applied_power)
            else:
                limit_ts = interval_start + timedelta(seconds=max(0.0, time_to_limit_seconds))
                self._apply_segment(interval_start, limit_ts, applied_power)
                self._stored_energy_kwh = self._energy_max_kwh
                self._update_soc_from_energy()
                self._current_applied_power_kw = 0.0

        else:
            available_energy = self._stored_energy_kwh - self._energy_min_kwh
            if available_energy <= EPSILON:
                self._current_applied_power_kw = 0.0
                self._last_update_ts = now
                self._prune_history(now)
                return

            discharge_rate_kwh_per_hour = (-applied_power) / self._config.efficiency
            time_to_limit_seconds = available_energy / discharge_rate_kwh_per_hour * 3600.0

            if time_to_limit_seconds >= interval_seconds - EPSILON:
                self._apply_segment(interval_start, interval_end, applied_power)
            else:
                limit_ts = interval_start + timedelta(seconds=max(0.0, time_to_limit_seconds))
                self._apply_segment(interval_start, limit_ts, applied_power)
                self._stored_energy_kwh = self._energy_min_kwh
                self._update_soc_from_energy()
                self._current_applied_power_kw = 0.0

        self._last_update_ts = now
        self._prune_history(now)

    def _apply_segment(self, start: datetime, end: datetime, power_kw: float) -> None:
        seconds = (end - start).total_seconds()
        if seconds <= EPSILON:
            return

        hours = seconds / 3600.0

        if power_kw >= 0:
            delta_stored_kwh = power_kw * self._config.efficiency * hours
        else:
            delta_stored_kwh = power_kw / self._config.efficiency * hours

        self._stored_energy_kwh += delta_stored_kwh
        self._stored_energy_kwh = min(max(self._stored_energy_kwh, self._energy_min_kwh), self._energy_max_kwh)
        self._update_soc_from_energy()
        self._record_segment(start, end, power_kw)

    def _window_energies(self, now: datetime, window_seconds: int) -> tuple[float, float]:
        window_start = now - timedelta(seconds=window_seconds)
        charged_kwh = 0.0
        discharged_kwh = 0.0

        for segment in self._history:
            overlap_start = max(segment.start, window_start)
            overlap_end = min(segment.end, now)
            overlap_seconds = (overlap_end - overlap_start).total_seconds()
            if overlap_seconds <= EPSILON:
                continue

            overlap_hours = overlap_seconds / 3600.0
            if segment.power_kw > 0:
                charged_kwh += segment.power_kw * overlap_hours
            elif segment.power_kw < 0:
                discharged_kwh += (-segment.power_kw) * overlap_hours

        return charged_kwh, discharged_kwh

    def _record_segment(self, start: datetime, end: datetime, power_kw: float) -> None:
        if isclose(power_kw, 0.0, abs_tol=EPSILON):
            return

        if self._history and isclose(self._history[-1].power_kw, power_kw, abs_tol=EPSILON):
            last = self._history[-1]
            if abs((start - last.end).total_seconds()) <= EPSILON:
                last.end = end
                return

        self._history.append(PowerSegment(start=start, end=end, power_kw=power_kw))

    def _prune_history(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self._config.max_observation_window_seconds)
        pruned: list[PowerSegment] = []

        for segment in self._history:
            if segment.end <= cutoff:
                continue
            if segment.start < cutoff:
                pruned.append(PowerSegment(start=cutoff, end=segment.end, power_kw=segment.power_kw))
            else:
                pruned.append(segment)

        self._history = pruned

    def _update_soc_from_energy(self) -> None:
        self._soc_pct = (self._stored_energy_kwh / self._config.capacity_kwh) * 100.0

    @staticmethod
    def _mode_for_power(power_kw: float) -> str:
        if power_kw > EPSILON:
            return "charging"
        if power_kw < -EPSILON:
            return "discharging"
        return "idle"

    @staticmethod
    def _append_reason(reasons: list[str], reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    @staticmethod
    def _ensure_aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Datetime must be timezone-aware")
        return value.astimezone(timezone.utc)
