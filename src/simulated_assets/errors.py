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
