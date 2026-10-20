"""统一的 API 异常类型。

接口错误响应始终保持同一种结构，便于前端稳定处理：

    {
      "ok": false,
      "error": {
        "code": "VALIDATION_ERROR",
        "message": "给她的名字不能为空。",
        "details": {...}       # 可选
      }
    }
"""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """业务层主动抛出的、可安全展示给前端的异常。"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "BAD_REQUEST",
        status_code: int = 400,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            error["details"] = self.details
        return {"ok": False, "error": error}
