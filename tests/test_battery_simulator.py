from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from simulated_assets.config import BatteryConfig
from simulated_assets.domain import ApplyPowerAction, ResetSocAction
from simulated_assets.errors import InvalidSocError, InvalidWindowError
from simulated_assets.simulators import BatterySimulator


def make_config(asset_id: str = "battery-1", **overrides: float | int | str) -> BatteryConfig:
    data: dict[str, float | int | str] = {
        "asset_id": asset_id,
        "asset_type": "home_battery",
        "capacity_kwh": 10.0,
        "initial_soc_pct": 50.0,
        "soc_min_pct": 0.0,
        "soc_max_pct": 100.0,
        "max_charge_power_kw": 5.0,
        "min_charge_power_kw": 0.5,
        "max_discharge_power_kw": 5.0,
        "min_discharge_power_kw": 0.5,
        "efficiency": 1.0,
        "default_observation_window_seconds": 300,
        "max_observation_window_seconds": 7200,
    }
    data.update(overrides)
    return BatteryConfig.model_validate(data)


def ts(base: datetime, seconds: int) -> datetime:
    return base + timedelta(seconds=seconds)


def test_charge_increases_soc() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    simulator = BatterySimulator(make_config(), start_time=start)

    simulator.apply_action(start, ApplyPowerAction(power_kw=2.0))
    observation = simulator.get_observation(ts(start, 3600), window_seconds=3600)

    assert observation.soc_pct == pytest.approx(70.0)
    assert observation.energy_charged_kwh_window == pytest.approx(2.0)
    assert observation.energy_discharged_kwh_window == pytest.approx(0.0)
    assert observation.instantaneous_power_kw == pytest.approx(2.0)


def test_discharge_decreases_soc() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    simulator = BatterySimulator(make_config(initial_soc_pct=80.0), start_time=start)

    simulator.apply_action(start, ApplyPowerAction(power_kw=-2.0))
    observation = simulator.get_observation(ts(start, 3600), window_seconds=3600)

    assert observation.soc_pct == pytest.approx(60.0)
    assert observation.energy_charged_kwh_window == pytest.approx(0.0)
    assert observation.energy_discharged_kwh_window == pytest.approx(2.0)
    assert observation.instantaneous_power_kw == pytest.approx(-2.0)


def test_efficiency_affects_stored_energy() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    simulator = BatterySimulator(make_config(efficiency=0.8), start_time=start)

    simulator.apply_action(start, ApplyPowerAction(power_kw=1.0))
    first_hour = simulator.get_observation(ts(start, 3600), window_seconds=3600)
    assert first_hour.soc_pct == pytest.approx(58.0)

    simulator.apply_action(ts(start, 3600), ApplyPowerAction(power_kw=-1.0))
    second_hour = simulator.get_observation(ts(start, 7200), window_seconds=3600)

    assert second_hour.soc_pct == pytest.approx(45.5)
    assert second_hour.energy_discharged_kwh_window == pytest.approx(1.0)


def test_saturates_when_reaching_soc_max() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    simulator = BatterySimulator(
        make_config(initial_soc_pct=95.0, soc_min_pct=0.0, soc_max_pct=100.0),
        start_time=start,
    )

    simulator.apply_action(start, ApplyPowerAction(power_kw=5.0))
    observation = simulator.get_observation(ts(start, 3600), window_seconds=3600)

    assert observation.soc_pct == pytest.approx(100.0)
    assert observation.energy_charged_kwh_window == pytest.approx(0.5)
    assert observation.instantaneous_power_kw == pytest.approx(0.0)
    assert observation.mode == "idle"


def test_saturates_when_reaching_soc_min() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    simulator = BatterySimulator(
        make_config(initial_soc_pct=15.0, soc_min_pct=10.0, soc_max_pct=100.0),
        start_time=start,
    )

    simulator.apply_action(start, ApplyPowerAction(power_kw=-5.0))
    observation = simulator.get_observation(ts(start, 3600), window_seconds=3600)

    assert observation.soc_pct == pytest.approx(10.0)
    assert observation.energy_discharged_kwh_window == pytest.approx(0.5)
    assert observation.instantaneous_power_kw == pytest.approx(0.0)
    assert observation.mode == "idle"


def test_deadband_for_minimum_charge_power() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    simulator = BatterySimulator(make_config(min_charge_power_kw=1.5), start_time=start)

    result = simulator.apply_action(start, ApplyPowerAction(power_kw=1.0))

    assert result.applied_power_kw == pytest.approx(0.0)
    assert result.was_saturated is True
    assert "below_min_charge_power_deadband" in result.saturation_reasons


def test_setpoint_persists_until_new_action() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    simulator = BatterySimulator(make_config(), start_time=start)

    simulator.apply_action(start, ApplyPowerAction(power_kw=2.0))

    half_hour = simulator.get_observation(ts(start, 1800), window_seconds=1800)
    one_hour = simulator.get_observation(ts(start, 3600), window_seconds=1800)

    assert half_hour.soc_pct == pytest.approx(60.0)
    assert one_hour.soc_pct == pytest.approx(70.0)


def test_dt_zero_does_not_change_state() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    simulator = BatterySimulator(make_config(), start_time=start)

    simulator.apply_action(start, ApplyPowerAction(power_kw=2.0))
    observation = simulator.get_observation(start, window_seconds=10)

    assert observation.soc_pct == pytest.approx(50.0)
    assert observation.energy_charged_kwh_window == pytest.approx(0.0)


def test_window_accumulates_partial_overlap_only() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    simulator = BatterySimulator(make_config(), start_time=start)

    simulator.apply_action(start, ApplyPowerAction(power_kw=2.0))
    simulator.apply_action(ts(start, 1800), ApplyPowerAction(power_kw=0.0))
    simulator.apply_action(ts(start, 3600), ApplyPowerAction(power_kw=-1.0))

    observation = simulator.get_observation(ts(start, 5400), window_seconds=3600)

    assert observation.energy_charged_kwh_window == pytest.approx(0.0)
    assert observation.energy_discharged_kwh_window == pytest.approx(0.5)
    assert observation.net_energy_kwh_window == pytest.approx(-0.5)
    assert observation.soc_pct == pytest.approx(55.0)


def test_window_larger_than_uptime_is_reported_as_effective_window() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    simulator = BatterySimulator(make_config(max_observation_window_seconds=2000), start_time=start)

    observation = simulator.get_observation(ts(start, 100), window_seconds=1000)

    assert observation.window_seconds_requested == 1000
    assert observation.window_seconds_effective == 100


def test_invalid_window_raises_error() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    simulator = BatterySimulator(make_config(max_observation_window_seconds=300), start_time=start)

    with pytest.raises(InvalidWindowError):
        simulator.get_observation(ts(start, 10), window_seconds=301)

    with pytest.raises(InvalidWindowError):
        simulator.get_observation(ts(start, 10), window_seconds=0)


def test_reset_soc_sets_requested_state_and_clears_power_history() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    simulator = BatterySimulator(make_config(), start_time=start)

    simulator.apply_action(start, ApplyPowerAction(power_kw=2.0))
    result = simulator.reset_soc(ts(start, 1800), ResetSocAction(soc_pct=30.0))

    assert result.requested_soc_pct == pytest.approx(30.0)
    assert result.soc_pct == pytest.approx(30.0)
    assert result.stored_energy_kwh == pytest.approx(3.0)
    assert result.applied_power_kw == pytest.approx(0.0)

    observation = simulator.get_observation(ts(start, 1800), window_seconds=1800)
    assert observation.soc_pct == pytest.approx(30.0)
    assert observation.instantaneous_power_kw == pytest.approx(0.0)
    assert observation.energy_charged_kwh_window == pytest.approx(0.0)
    assert observation.energy_discharged_kwh_window == pytest.approx(0.0)
    assert observation.window_seconds_effective == 0


def test_reset_soc_rejects_outside_allowed_range() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    simulator = BatterySimulator(
        make_config(initial_soc_pct=50.0, soc_min_pct=10.0, soc_max_pct=90.0),
        start_time=start,
    )

    with pytest.raises(InvalidSocError):
        simulator.reset_soc(start, ResetSocAction(soc_pct=5.0))

    with pytest.raises(InvalidSocError):
        simulator.reset_soc(start, ResetSocAction(soc_pct=95.0))
