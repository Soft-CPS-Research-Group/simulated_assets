from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone

import holidays

from simulated_assets.config import GridMeterConfig
from simulated_assets.domain import (
    ActionResult,
    ApplyPowerAction,
    AssetSimulator,
    GridMeterObservationResult,
    ResetResult,
    ResetSocAction,
)
from simulated_assets.errors import InvalidWindowError, UnsupportedOperationError

WORKDAY_NIGHT_WEIGHT = 0.10
WORKDAY_MORNING_WEIGHT = 0.60
WORKDAY_DAY_WEIGHT = 1.00
WORKDAY_EVENING_WEIGHT = 0.40
WEEKEND_OR_HOLIDAY_WEIGHT = 0.05
MONTHLY_TARGET_KWH = 13000.0


class GridMeterSimulator(AssetSimulator):
    def __init__(self, config: GridMeterConfig, start_time: datetime) -> None:
        self._config = config
        self._started_at = self._ensure_aware(start_time)
        self._monthly_base_kw_cache: dict[tuple[int, int], float] = {}
        self._holidays_by_year: dict[int, set[date]] = {}

    def apply_action(self, now: datetime, action: ApplyPowerAction) -> ActionResult:
        raise UnsupportedOperationError(asset_type=self._config.asset_type, operation="apply_action")

    def get_observation(
        self,
        now: datetime,
        window_seconds: int | None,
    ) -> GridMeterObservationResult:
        now = self._ensure_aware(now)
        resolved_window = self._resolve_window_seconds(window_seconds)

        uptime_seconds = max(0, int((now - self._started_at).total_seconds()))
        effective_window = min(resolved_window, uptime_seconds)
        if effective_window <= 0:
            return self._empty_observation()

        window_start = now - timedelta(seconds=effective_window)
        energy_in_total = self._integrate_energy(window_start, now)

        return GridMeterObservationResult(
            energy_in_total=energy_in_total,
            energy_in_l1=None,
            energy_in_l2=None,
            energy_in_l3=None,
            energy_out_total=0.0,
            energy_out_l1=None,
            energy_out_l2=None,
            energy_out_l3=None,
        )

    def reset_soc(self, now: datetime, action: ResetSocAction) -> ResetResult:
        raise UnsupportedOperationError(asset_type=self._config.asset_type, operation="reset_soc")

    def _resolve_window_seconds(self, window_seconds: int | None) -> int:
        if window_seconds is None:
            return self._config.default_observation_window_seconds
        if window_seconds < 1 or window_seconds > self._config.max_observation_window_seconds:
            raise InvalidWindowError(window_seconds, self._config.max_observation_window_seconds)
        return window_seconds

    def _integrate_energy(self, start: datetime, end: datetime) -> float:
        if start >= end:
            return 0.0

        cursor = start
        total_energy_kwh = 0.0

        while cursor < end:
            segment_end = min(end, self._next_boundary(cursor))
            segment_hours = (segment_end - cursor).total_seconds() / 3600.0
            weight = self._weight_for_timestamp(cursor)
            base_kw = self._base_kw_for_month(cursor.year, cursor.month)
            total_energy_kwh += base_kw * weight * segment_hours
            cursor = segment_end

        return total_energy_kwh

    def _next_boundary(self, ts: datetime) -> datetime:
        day_start = datetime(ts.year, ts.month, ts.day, tzinfo=timezone.utc)
        next_midnight = day_start + timedelta(days=1)
        next_month_start = self._next_month_start(ts)

        candidates = [next_midnight, next_month_start]
        for hour in (8, 9, 17, 19):
            boundary = day_start + timedelta(hours=hour)
            if boundary > ts:
                candidates.append(boundary)

        return min(candidates)

    def _weight_for_timestamp(self, ts: datetime) -> float:
        if self._is_weekend_or_holiday(ts.date()):
            return WEEKEND_OR_HOLIDAY_WEIGHT

        hour = ts.hour
        if hour < 8:
            return WORKDAY_NIGHT_WEIGHT
        if hour < 9:
            return WORKDAY_MORNING_WEIGHT
        if hour < 17:
            return WORKDAY_DAY_WEIGHT
        if hour < 19:
            return WORKDAY_EVENING_WEIGHT
        return WORKDAY_NIGHT_WEIGHT

    def _base_kw_for_month(self, year: int, month: int) -> float:
        cache_key = (year, month)
        cached = self._monthly_base_kw_cache.get(cache_key)
        if cached is not None:
            return cached

        weighted_hours = self._weighted_hours_for_month(year, month)
        base_kw = MONTHLY_TARGET_KWH / weighted_hours
        self._monthly_base_kw_cache[cache_key] = base_kw
        return base_kw

    def _weighted_hours_for_month(self, year: int, month: int) -> float:
        _, month_days = calendar.monthrange(year, month)
        weighted_hours = 0.0

        for day in range(1, month_days + 1):
            current_date = date(year, month, day)
            if self._is_weekend_or_holiday(current_date):
                weighted_hours += 24.0 * WEEKEND_OR_HOLIDAY_WEIGHT
            else:
                weighted_hours += (
                    8.0 * WORKDAY_NIGHT_WEIGHT
                    + 1.0 * WORKDAY_MORNING_WEIGHT
                    + 8.0 * WORKDAY_DAY_WEIGHT
                    + 2.0 * WORKDAY_EVENING_WEIGHT
                    + 5.0 * WORKDAY_NIGHT_WEIGHT
                )

        return weighted_hours

    def _is_weekend_or_holiday(self, value: date) -> bool:
        if value.weekday() >= 5:
            return True
        return value in self._holidays_for_year(value.year)

    def _holidays_for_year(self, year: int) -> set[date]:
        cached = self._holidays_by_year.get(year)
        if cached is not None:
            return cached

        pt_holidays = holidays.country_holidays("PT", years=[year])
        holiday_dates = set(pt_holidays.keys())
        self._holidays_by_year[year] = holiday_dates
        return holiday_dates

    @staticmethod
    def _next_month_start(ts: datetime) -> datetime:
        if ts.month == 12:
            return datetime(ts.year + 1, 1, 1, tzinfo=timezone.utc)
        return datetime(ts.year, ts.month + 1, 1, tzinfo=timezone.utc)

    @staticmethod
    def _empty_observation() -> GridMeterObservationResult:
        return GridMeterObservationResult(
            energy_in_total=0.0,
            energy_in_l1=None,
            energy_in_l2=None,
            energy_in_l3=None,
            energy_out_total=0.0,
            energy_out_l1=None,
            energy_out_l2=None,
            energy_out_l3=None,
        )

    @staticmethod
    def _ensure_aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Datetime must be timezone-aware")
        return value.astimezone(timezone.utc)
