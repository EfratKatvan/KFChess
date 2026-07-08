from __future__ import annotations
ERROR_ROW_WIDTH_MISMATCH = "ERROR ROW_WIDTH_MISMATCH"
ERROR_UNKNOWN_TOKEN = "ERROR UNKNOWN_TOKEN"


class BoardValidationError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code