from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from simulated_assets.app import create_app
from simulated_assets.config import BatteryConfig
from simulated_assets.registry import AssetRegistry


class ManualClock:
    def __init__(self, start: datetime) -> None:
        self.current = start

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current = self.current + timedelta(seconds=seconds)


def make_config(asset_id: str, **overrides: float | int | str) -> BatteryConfig:
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
        "max_observation_window_seconds": 3600,
    }
    data.update(overrides)
    return BatteryConfig.model_validate(data)


def build_client() -> tuple[TestClient, ManualClock]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = ManualClock(start)

    configs = [
        make_config("battery-a"),
        make_config("battery-b"),
    ]

    registry = AssetRegistry.from_configs(configs, start_time=clock())
    app = create_app(registry=registry, clock=clock)
    return TestClient(app), clock


def test_apply_action_then_get_observation_flow() -> None:
    client, clock = build_client()

    apply_response = client.post("/assets/battery-a/actions", json={"power_kw": 2.0})
    assert apply_response.status_code == 200
    apply_payload = apply_response.json()
    assert apply_payload["requested_power_kw"] == 2.0
    assert apply_payload["applied_power_kw"] == 2.0
    assert apply_payload["was_saturated"] is False

    clock.advance(1800)

    observe_response = client.get("/assets/battery-a/observations", params={"window_seconds": 1800})
    assert observe_response.status_code == 200
    observe_payload = observe_response.json()

    assert observe_payload["instantaneous_power_kw"] == 2.0
    assert observe_payload["soc_pct"] == 60.0
    assert observe_payload["energy_charged_kwh_window"] == 1.0
    assert observe_payload["energy_discharged_kwh_window"] == 0.0
    assert observe_payload["net_energy_kwh_window"] == 1.0


def test_get_observation_returns_404_for_unknown_asset() -> None:
    client, _ = build_client()

    response = client.get("/assets/missing/observations")

    assert response.status_code == 404


def test_get_observation_returns_400_for_invalid_window() -> None:
    client, _ = build_client()

    response = client.get("/assets/battery-a/observations", params={"window_seconds": 9999})

    assert response.status_code == 400
    assert "window_seconds" in response.json()["detail"]


def test_apply_action_returns_422_for_invalid_payload() -> None:
    client, _ = build_client()

    response = client.post("/assets/battery-a/actions", json={"power": 2.0})

    assert response.status_code == 422


def test_assets_are_isolated_by_asset_id() -> None:
    client, clock = build_client()

    first_apply = client.post("/assets/battery-a/actions", json={"power_kw": 2.0})
    assert first_apply.status_code == 200

    clock.advance(3600)

    first_observation = client.get("/assets/battery-a/observations", params={"window_seconds": 3600})
    second_observation = client.get("/assets/battery-b/observations", params={"window_seconds": 3600})

    assert first_observation.status_code == 200
    assert second_observation.status_code == 200

    assert first_observation.json()["soc_pct"] == 70.0
    assert second_observation.json()["soc_pct"] == 50.0
