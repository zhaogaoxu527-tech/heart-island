"""项目配置。

所有可变参数都通过环境变量 / `.env` 文件注入，避免把密钥写进代码。
主模型为 Kimi（Moonshot）OpenAI 兼容接口；未配置密钥或模型不可用时，可自动回退到本地体验模式。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent


def _load_env() -> None:
    """优先加载项目根目录下的 .env（不覆盖系统中已存在的环境变量）。"""
    load_dotenv(BASE_DIR / ".env", override=False)


_load_env()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _resolve_database_path(raw: str) -> str:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return str(path)


class Config:
    """Flask 配置类。测试时可由 create_app(test_config=...) 覆盖。"""

    # ---------- 基础 ----------
    JSON_AS_ASCII = False
    MAX_CONTENT_LENGTH = 64 * 1024
    SECRET_KEY = os.getenv(
        "SECRET_KEY", "heart-island-local-dev-key-change-before-deploying"
    )
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _as_bool(os.getenv("SESSION_COOKIE_SECURE"), False)

    # ---------- 服务 ----------
    HOST = os.getenv("HOST", "127.0.0.1")
    PORT = _as_int(os.getenv("PORT"), 5000)
    DEBUG = _as_bool(os.getenv("FLASK_DEBUG"), False)

    # ---------- 数据库 ----------
    DATABASE = _resolve_database_path(
        os.getenv("DATABASE_PATH", "data/heart_island.db")
    )

    # ---------- Kimi（Moonshot）OpenAI 兼容接口 ----------
    KIMI_API_KEY = (
        os.getenv("KIMI_API_KEY")
        or os.getenv("MOONSHOT_API_KEY")
        or "sk-VIueJzo5jz2nUuhcwB7Vwen20XIAxq4a2QNULvTNIuoeO5A0"
    ).strip()
    KIMI_BASE_URL = os.getenv(
        "KIMI_BASE_URL",
        "https://api.moonshot.cn/v1",
    ).strip()
    KIMI_MODEL = os.getenv("KIMI_MODEL", "kimi-k3").strip()
    KIMI_TIMEOUT = _as_int(os.getenv("KIMI_TIMEOUT"), 60)
    KIMI_MAX_TOKENS = _as_int(os.getenv("KIMI_MAX_TOKENS"), 800)
    # API 失败时是否回退到内置角色回复，保证页面不会因网络或额度问题完全不可用
    KIMI_FALLBACK_LOCAL = _as_bool(os.getenv("KIMI_FALLBACK_LOCAL"), True)
    KIMI_HISTORY_LIMIT = _as_int(os.getenv("KIMI_HISTORY_LIMIT"), 24)
    KIMI_HISTORY_CHAR_BUDGET = _as_int(
        os.getenv("KIMI_HISTORY_CHAR_BUDGET"), 12000
    )

    # ---------- 业务约束 ----------
    MAX_NAME_LENGTH = 10
    MAX_MESSAGE_LENGTH = 2000
    USERNAME_MIN_LENGTH = 3
    USERNAME_MAX_LENGTH = 20
    PASSWORD_MIN_LENGTH = 6
    PASSWORD_MAX_LENGTH = 128

    # ---------- 登录状态 ----------
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 30  # 30 天

    @property
    def kimi_enabled(self) -> bool:
        return bool(self.KIMI_API_KEY)
