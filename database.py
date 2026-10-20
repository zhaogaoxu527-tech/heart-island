"""SQLite 连接管理与初始化。

设计要点：
1. 每个 Flask 请求使用独立连接，请求结束自动关闭，线程安全。
2. 开启外键约束与 WAL，兼顾数据完整性和并发读性能。
3. 表结构集中在 schema.sql，方便交付、审阅与手工建库。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import Flask, current_app, g


def get_db() -> sqlite3.Connection:
    """获取当前请求的数据库连接（不存在则创建）。"""
    if "db" not in g:
        db_path = current_app.config["DATABASE"]
        # 测试环境可能使用临时目录；确保父目录存在。
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(db_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        g.db = connection
    return g.db


def close_db(_error: BaseException | None = None) -> None:
    """请求结束时关闭连接，避免连接泄漏。"""
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db() -> None:
    """执行 schema.sql。脚本使用 IF NOT EXISTS，可安全重复调用。"""
    db = get_db()
    schema_path = Path(current_app.root_path) / "schema.sql"
    with schema_path.open("r", encoding="utf-8") as schema_file:
        db.executescript(schema_file.read())
    db.commit()


def init_app(app: Flask) -> None:
    """把数据库生命周期挂到 Flask 应用上。"""
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
