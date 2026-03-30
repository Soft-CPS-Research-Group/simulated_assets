from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from simulated_assets.config import GridMeterConfig
from simulated_assets.domain import ApplyPowerAction, ResetSocAction
from simulated_assets.errors import InvalidWindowError, UnsupportedOperationError
from simulated_assets.simulators import GridMeterSimulator


def make_config(asset_id: str = "grid-1", **overrides: float | int | str) -> GridMeterConfig:
    data: dict[str, float | int | str] = {
        "asset_id": asset_id,
        "asset_type": "grid_meter",
        "default_observation_window_seconds": 300,
        "max_observation_window_seconds": 4_000_000,
    }
    data.update(overrides)
    return GridMeterConfig.model_validate(data)


def ts(base: datetime, seconds: int) -> datetime:
    return base + timedelta(seconds=seconds)


def test_weekday_profile_uses_expected_hourly_weights() -> None:
    # 2026-01-07 is a Wednesday (non-holiday in PT)
    start = datetime(2026, 1, 7, tzinfo=timezone.utc)
    simulator = GridMeterSimulator(make_config(), start_time=start)

    night_hour = simulator.get_observation(ts(start, 8 * 3600), window_seconds=3600)
    morning_hour = simulator.get_observation(ts(start, 9 * 3600), window_seconds=3600)
    peak_hour = simulator.get_observation(ts(start, 10 * 3600), window_seconds=3600)
    evening_hour = simulator.get_observation(ts(start, 18 * 3600), window_seconds=3600)

    assert peak_hour.energy_in_total > 0
    assert night_hour.energy_in_total / peak_hour.energy_in_total == pytest.approx(0.10)
    assert morning_hour.energy_in_total / peak_hour.energy_in_total == pytest.approx(0.60)
    assert evening_hour.energy_in_total / peak_hour.energy_in_total == pytest.approx(0.40)


def test_weekend_and_holiday_use_residual_weight() -> None:
    weekday_start = datetime(2026, 1, 7, tzinfo=timezone.utc)
    weekday_simulator = GridMeterSimulator(make_config(), start_time=weekday_start)
    weekday_peak_hour = weekday_simulator.get_observation(
        ts(weekday_start, 10 * 3600),
        window_seconds=3600,
    )

    holiday_start = datetime(2026, 1, 1, tzinfo=timezone.utc)  # PT holiday
    holiday_simulator = GridMeterSimulator(make_config(), start_time=holiday_start)
    holiday_hour = holiday_simulator.get_observation(
        ts(holiday_start, 12 * 3600),
        window_seconds=3600,
    )

    weekend_start = datetime(2026, 1, 10, tzinfo=timezone.utc)  # Saturday
    weekend_simulator = GridMeterSimulator(make_config(), start_time=weekend_start)
    weekend_hour = weekend_simulator.get_observation(
        ts(weekend_start, 12 * 3600),
        window_seconds=3600,
    )

    assert holiday_hour.energy_in_total / weekday_peak_hour.energy_in_total == pytest.approx(0.05)
    assert weekend_hour.energy_in_total / weekday_peak_hour.energy_in_total == pytest.approx(0.05)


def test_month_window_is_calibrated_to_13000_kwh() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    simulator = GridMeterSimulator(make_config(), start_time=start)

    january_seconds = 31 * 24 * 3600
    observation = simulator.get_observation(ts(start, january_seconds), window_seconds=january_seconds)

    assert observation.energy_in_total == pytest.approx(13000.0, rel=1e-6)


def test_window_larger_than_uptime_is_effectively_truncated() -> None:
    start = datetime(2026, 1, 7, tzinfo=timezone.utc)
    short_uptime_sim = GridMeterSimulator(make_config(), start_time=start)
    full_hour_sim = GridMeterSimulator(make_config(), start_time=start)

    partial = short_uptime_sim.get_observation(ts(start, 600), window_seconds=3600)
    full = full_hour_sim.get_observation(ts(start, 3600), window_seconds=3600)

    assert partial.energy_in_total * 6.0 == pytest.approx(full.energy_in_total)


def test_invalid_window_raises_error() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    simulator = GridMeterSimulator(
        make_config(default_observation_window_seconds=300, max_observation_window_seconds=900),
        start_time=start,
    )

    with pytest.raises(InvalidWindowError):
        simulator.get_observation(ts(start, 10), window_seconds=0)

    with pytest.raises(InvalidWindowError):
        simulator.get_observation(ts(start, 10), window_seconds=901)


def test_grid_meter_is_read_only() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    simulator = GridMeterSimulator(make_config(), start_time=start)

    with pytest.raises(UnsupportedOperationError):
        simulator.apply_action(start, ApplyPowerAction(power_kw=10.0))

    with pytest.raises(UnsupportedOperationError):
        simulator.reset_soc(start, ResetSocAction(soc_pct=50.0))


def test_grid_meter_returns_sample_shape_fields() -> None:
    start = datetime(2026, 1, 7, tzinfo=timezone.utc)
    simulator = GridMeterSimulator(make_config(), start_time=start)
    observation = simulator.get_observation(ts(start, 3600), window_seconds=3600)

    assert observation.energy_in_total > 0
    assert observation.energy_in_l1 is None
    assert observation.energy_in_l2 is None
    assert observation.energy_in_l3 is None
    assert observation.energy_out_total == pytest.approx(0.0)
    assert observation.energy_out_l1 is None
    assert observation.energy_out_l2 is None
    assert observation.energy_out_l3 is None
