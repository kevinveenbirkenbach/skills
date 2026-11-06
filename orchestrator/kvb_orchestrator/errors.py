from __future__ import annotations


class ToolError(Exception):
    pass


class Missing(Exception):
    pass


class Conflict(Exception):
    def __init__(self, payload: dict) -> None:
        super().__init__("conflict")
        self.payload = payload


class RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


class Unavailable(Exception):
    pass


class EngineError(Exception):
    pass
