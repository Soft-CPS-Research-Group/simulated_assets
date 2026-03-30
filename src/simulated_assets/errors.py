class AssetNotFoundError(Exception):
    def __init__(self, asset_id: str) -> None:
        super().__init__(f"Asset '{asset_id}' not found")
        self.asset_id = asset_id


class InvalidWindowError(Exception):
    def __init__(self, window_seconds: int, max_window_seconds: int) -> None:
        super().__init__(
            f"window_seconds must be in range [1, {max_window_seconds}], got {window_seconds}"
        )
        self.window_seconds = window_seconds
        self.max_window_seconds = max_window_seconds


class InvalidSocError(Exception):
    def __init__(self, soc_pct: float, soc_min_pct: float, soc_max_pct: float) -> None:
        super().__init__(
            f"soc_pct must be in range [{soc_min_pct}, {soc_max_pct}], got {soc_pct}"
        )
        self.soc_pct = soc_pct
        self.soc_min_pct = soc_min_pct
        self.soc_max_pct = soc_max_pct


class UnsupportedOperationError(Exception):
    def __init__(self, asset_type: str, operation: str) -> None:
        super().__init__(f"Operation '{operation}' is not supported for asset_type '{asset_type}'")
        self.asset_type = asset_type
        self.operation = operation
