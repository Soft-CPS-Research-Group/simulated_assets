from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from simulated_assets.domain import ApplyPowerAction, GridMeterObservationResult, ResetSocAction
from simulated_assets.errors import (
    AssetNotFoundError,
    InvalidSocError,
    InvalidWindowError,
    UnsupportedOperationError,
)
from simulated_assets.registry import AssetRegistry

Clock = Callable[[], datetime]


class ApplyActionRequest(BaseModel):
    power_kw: float


class ApplyActionResponse(BaseModel):
    requested_power_kw: float
    applied_power_kw: float
    was_saturated: bool
    saturation_reasons: list[str]
    soc_pct: float
    stored_energy_kwh: float
    timestamp: datetime


class ObservationResponse(BaseModel):
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


class GridMeterSampleResponse(BaseModel):
    energy_in_total: float
    energy_in_l1: float | None
    energy_in_l2: float | None
    energy_in_l3: float | None
    energy_out_total: float
    energy_out_l1: float | None
    energy_out_l2: float | None
    energy_out_l3: float | None


class GridMeterObservationResponse(BaseModel):
    GR01: GridMeterSampleResponse


class ResetSocRequest(BaseModel):
    soc_pct: float = Field(ge=0, le=100)


class ResetSocResponse(BaseModel):
    requested_soc_pct: float
    soc_pct: float
    stored_energy_kwh: float
    applied_power_kw: float
    timestamp: datetime


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def create_app(
    registry: AssetRegistry | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    clock_fn = clock or utc_now

    if registry is None:
        config_path = Path(os.getenv("SIMULATED_ASSETS_CONFIG", "config/assets.json"))
        registry = AssetRegistry.from_config_file(config_path=config_path, start_time=clock_fn())

    app = FastAPI(title="Simulated Assets API", version="0.1.0")

    @app.post("/assets/{asset_id}/actions", response_model=ApplyActionResponse)
    async def apply_action(asset_id: str, request: ApplyActionRequest) -> ApplyActionResponse:
        try:
            result = registry.apply_action(
                asset_id=asset_id,
                now=clock_fn(),
                action=ApplyPowerAction(power_kw=request.power_kw),
            )
        except AssetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except UnsupportedOperationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return ApplyActionResponse(
            requested_power_kw=result.requested_power_kw,
            applied_power_kw=result.applied_power_kw,
            was_saturated=result.was_saturated,
            saturation_reasons=result.saturation_reasons,
            soc_pct=result.soc_pct,
            stored_energy_kwh=result.stored_energy_kwh,
            timestamp=result.timestamp,
        )

    @app.get(
        "/assets/{asset_id}/observations",
        response_model=ObservationResponse | GridMeterObservationResponse,
    )
    async def get_observation(
        asset_id: str,
        window_seconds: int | None = Query(default=None),
    ) -> ObservationResponse | GridMeterObservationResponse:
        try:
            result = registry.get_observation(
                asset_id=asset_id,
                now=clock_fn(),
                window_seconds=window_seconds,
            )
        except AssetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InvalidWindowError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if isinstance(result, GridMeterObservationResult):
            return GridMeterObservationResponse(
                GR01=GridMeterSampleResponse(
                    energy_in_total=result.energy_in_total,
                    energy_in_l1=result.energy_in_l1,
                    energy_in_l2=result.energy_in_l2,
                    energy_in_l3=result.energy_in_l3,
                    energy_out_total=result.energy_out_total,
                    energy_out_l1=result.energy_out_l1,
                    energy_out_l2=result.energy_out_l2,
                    energy_out_l3=result.energy_out_l3,
                )
            )

        return ObservationResponse(
            instantaneous_power_kw=result.instantaneous_power_kw,
            mode=result.mode,
            soc_pct=result.soc_pct,
            stored_energy_kwh=result.stored_energy_kwh,
            window_seconds_requested=result.window_seconds_requested,
            window_seconds_effective=result.window_seconds_effective,
            energy_charged_kwh_window=result.energy_charged_kwh_window,
            energy_discharged_kwh_window=result.energy_discharged_kwh_window,
            net_energy_kwh_window=result.net_energy_kwh_window,
            timestamp=result.timestamp,
        )

    @app.post("/assets/{asset_id}/reset", response_model=ResetSocResponse)
    async def reset_soc(asset_id: str, request: ResetSocRequest) -> ResetSocResponse:
        try:
            result = registry.reset_soc(
                asset_id=asset_id,
                now=clock_fn(),
                action=ResetSocAction(soc_pct=request.soc_pct),
            )
        except AssetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InvalidSocError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except UnsupportedOperationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return ResetSocResponse(
            requested_soc_pct=result.requested_soc_pct,
            soc_pct=result.soc_pct,
            stored_energy_kwh=result.stored_energy_kwh,
            applied_power_kw=result.applied_power_kw,
            timestamp=result.timestamp,
        )

    return app
