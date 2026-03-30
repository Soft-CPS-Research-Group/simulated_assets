# simulated_assets

FastAPI service to simulate energy-community assets for real deployments.

## MVP scope

This repository currently implements two asset types:

- `home_battery`
- `grid_meter` (read-only)

Runtime API exposes three endpoints per `asset_id`:

- `POST /assets/{asset_id}/actions` to apply a power setpoint (`power_kw`)
- `GET /assets/{asset_id}/observations` to read state and windowed energy metrics
- `POST /assets/{asset_id}/reset` to reset battery SOC (`soc_pct`)

For `grid_meter`, only `GET /observations` is supported. `actions` and `reset` return `400`.

## Battery behavior

- `power_kw > 0`: charging
- `power_kw < 0`: discharging
- `power_kw = 0`: idle
- setpoint remains active until a new action arrives
- state evolves event-by-event using server time
- SOC is represented as percentage (`0..100`)
- efficiency is one-way and applied symmetrically as specified in the plan

## Configuration

Assets are loaded on startup from `config/assets.json` by default.
You can override the file path via:

- `SIMULATED_ASSETS_CONFIG=/path/to/assets.json`

Example config is provided in [config/assets.json](config/assets.json).

### `BatteryConfig` fields

- `asset_id`
- `asset_type` (`home_battery`)
- `capacity_kwh`
- `initial_soc_pct`
- `soc_min_pct`
- `soc_max_pct`
- `max_charge_power_kw`
- `min_charge_power_kw`
- `max_discharge_power_kw`
- `min_discharge_power_kw`
- `efficiency`
- `default_observation_window_seconds`
- `max_observation_window_seconds`

### `GridMeterConfig` fields

- `asset_id`
- `asset_type` (`grid_meter`)
- `default_observation_window_seconds`
- `max_observation_window_seconds`

Grid meter observations are returned in kWh using the sample shape:

```json
{
  "GR01": {
    "energy_in_total": 2.2,
    "energy_in_l1": null,
    "energy_in_l2": null,
    "energy_in_l3": null,
    "energy_out_total": 0.0,
    "energy_out_l1": null,
    "energy_out_l2": null,
    "energy_out_l3": null
  }
}
```

## Run

```bash
python3 -m pip install -e .
uvicorn simulated_assets.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 30
```

For pollers running at ~5s intervals, avoid using the default Uvicorn keep-alive timeout (`5s`), as it can intermittently close idle pooled connections right before the next request.

## Test

```bash
python3 -m pip install -e .[dev]
pytest
```

## CI/CD (GitHub Actions)

Workflow file: `.github/workflows/ci-cd.yml`

- Runs tests on every `push` and `pull_request`
- Publishes Docker image `latest` on every `push` after tests pass

Required repository secrets:

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`

## Postman

Postman artifact is available in `postman/`:

- `postman/simulated_assets.postman_collection.json`

Import the collection and run it directly.  
All required variables are already inside the collection (`baseUrl`, `assetId`, `windowSeconds`, `resetSocPct`).
