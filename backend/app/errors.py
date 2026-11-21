"""One error type so every failure has the same JSON shape:
{"error": {"code": "...", "message": "...", "details": ...}}"""
from __future__ import annotations

from typing import Any


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        super().__init__(message)


def not_found(what: str, ident: str) -> ApiError:
    return ApiError(404, f"{what}_not_found", f"No {what} with id '{ident}'.")
