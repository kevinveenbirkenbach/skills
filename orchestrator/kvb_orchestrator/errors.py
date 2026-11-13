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


class Held(Exception):
    def __init__(self, reason: str) -> None:
        """Args:
            reason: why the hub holds the request back, sent as {"reason"}.
        """
        super().__init__(reason)
        self.reason = reason


class EngineError(Exception):
    pass
