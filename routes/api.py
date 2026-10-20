"""AI 女友业务 API。

核心规则：
- 所有接口通过服务端 session 获取当前用户名，绝不信任前端传来的 username；
- 历史记录查询条件严格为 username + girl_name + girl_char（性格中文标签）；
- 三者任一不同，就会得到另一套独立记录；数据库不会混入旧记录；
- 每轮对话成功生成后，把用户消息与 AI 回复在同一事务中写入 chat_history。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, current_app, g, jsonify, request

from database import get_db
from errors import ApiError
from routes.auth import login_required
from services.llm_service import generate_reply, get_llm_status
from services.persona_service import (
    PERSONALITIES,
    build_persona_prompt,
    normalize_name,
    personality_code_from_label,
    public_personalities,
    resolve_girl_char,
    role_safe_reply,
)

bp = Blueprint("api", __name__, url_prefix="/api")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def success(data: Any = None, status: int = 200):
    return jsonify({"ok": True, "data": data}), status


def require_json() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(
            "请求格式不正确，请使用 JSON 提交。",
            code="INVALID_JSON",
            status_code=400,
        )
    return data


def serialize_history_item(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "create_time": row["create_time"],
    }


def resolve_persona_or_fail(girl_name_raw: Any, girl_char_raw: Any) -> dict[str, Any]:
    girl_name = normalize_name(girl_name_raw)
    code, label = resolve_girl_char(girl_char_raw)
    return {
        "code": code,
        "label": label,
        "name": girl_name,
        "tagline": PERSONALITIES[code]["tagline"],
        "quote": PERSONALITIES[code]["quote"],
    }


def fetch_history(
    db: sqlite3.Connection, username: str, girl_name: str, girl_char: str
) -> list[sqlite3.Row]:
    return db.execute(
        """
        SELECT id, username, girl_name, girl_char, role, content, create_time
        FROM chat_history
        WHERE username = ? AND girl_name = ? AND girl_char = ?
        ORDER BY id ASC
        """,
        (username, girl_name, girl_char),
    ).fetchall()


def load_model_context(
    db: sqlite3.Connection, username: str, girl_name: str, girl_char: str
) -> list[dict[str, str]]:
    """只把最近 N 条 / 预算内的历史交给模型，避免上下文无限增长。

    加载给前端的历史仍然是全量；这里只限制模型输入。
    """
    limit = max(1, int(current_app.config["KIMI_HISTORY_LIMIT"]))
    budget = max(1000, int(current_app.config["KIMI_HISTORY_CHAR_BUDGET"]))
    rows = db.execute(
        """
        SELECT role, content
        FROM chat_history
        WHERE username = ? AND girl_name = ? AND girl_char = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (username, girl_name, girl_char, limit),
    ).fetchall()

    selected: list[dict[str, str]] = []
    used = 0
    for row in rows:
        length = len(row["content"])
        if selected and used + length > budget:
            break
        selected.append({"role": row["role"], "content": row["content"]})
        used += length
    selected.reverse()
    return selected


# ---------------------------------------------------------------------------
# 基础 / 性格配置
# ---------------------------------------------------------------------------
@bp.get("/health")
def health():
    return success(
        {
            "status": "ok",
            "server_time": utc_now(),
            "llm": get_llm_status(),
        }
    )


@bp.get("/personalities")
def personalities():
    return success({"items": public_personalities()})


# ---------------------------------------------------------------------------
# 历史记录
# ---------------------------------------------------------------------------
@bp.get("/history")
@login_required
def get_history():
    """返回当前用户在一套「女友名 + 性格」下的全部聊天记录。"""
    persona = resolve_persona_or_fail(
        request.args.get("girl_name"), request.args.get("girl_char")
    )
    username = g.current_user["username"]
    db = get_db()
    rows = fetch_history(db, username, persona["name"], persona["label"])

    return success(
        {
            "persona": {
                "girl_name": persona["name"],
                "girl_char": persona["label"],
                "personality": persona["code"],
                "tagline": persona["tagline"],
                "quote": persona["quote"],
            },
            "items": [serialize_history_item(row) for row in rows],
            "total": len(rows),
        }
    )


@bp.get("/chat/recent")
@login_required
def recent_persona():
    """返回当前用户最近使用过的一套人设，用于首页「继续上次对话」。"""
    username = g.current_user["username"]
    db = get_db()
    row = db.execute(
        """
        SELECT girl_name, girl_char, COUNT(*) AS message_count,
               MAX(id) AS last_id, MAX(create_time) AS last_time
        FROM chat_history
        WHERE username = ?
        GROUP BY girl_name, girl_char
        ORDER BY last_id DESC
        LIMIT 1
        """,
        (username,),
    ).fetchone()
    if row is None:
        return success({"persona": None})

    code = personality_code_from_label(row["girl_char"])
    if code is None and row["girl_char"] in PERSONALITIES:
        code = row["girl_char"]
    preset = PERSONALITIES.get(code or "", {})
    label = preset.get("label", row["girl_char"])
    return success(
        {
            "persona": {
                "girl_name": row["girl_name"],
                "girl_char": label,
                "personality": code,
                "tagline": preset.get("tagline", ""),
                "quote": preset.get("quote", ""),
                "message_count": row["message_count"],
                "last_time": row["last_time"],
            }
        }
    )


# ---------------------------------------------------------------------------
# 聊天
# ---------------------------------------------------------------------------
@bp.post("/chat")
@login_required
def chat():
    """生成一轮回复，并把用户消息 + AI 回复写入 chat_history。

    只有模型/本地回复生成成功后才写数据库，因此不会出现“只有提问没有回复”的残局。
    """
    payload = require_json()
    persona = resolve_persona_or_fail(
        payload.get("girl_name"), payload.get("girl_char")
    )
    raw_message = payload.get("message")
    if not isinstance(raw_message, str):
        raise ApiError(
            "消息内容是必填的。", code="VALIDATION_ERROR", status_code=422
        )
    message = raw_message.replace("\x00", "").strip()
    if not message:
        raise ApiError(
            "写点什么再发给她吧。", code="VALIDATION_ERROR", status_code=422
        )
    if len(message) > current_app.config["MAX_MESSAGE_LENGTH"]:
        raise ApiError(
            f"单条消息最多 {current_app.config['MAX_MESSAGE_LENGTH']} 个字符。",
            code="MESSAGE_TOO_LONG",
            status_code=422,
        )

    username = g.current_user["username"]
    db = get_db()
    history = load_model_context(db, username, persona["name"], persona["label"])
    system_prompt = build_persona_prompt(persona["name"], persona["code"])
    llm_messages = [{"role": "system", "content": system_prompt}]
    llm_messages.extend(history)
    llm_messages.append({"role": "user", "content": message})

    reply_text, mode = generate_reply(
        messages=llm_messages,
        personality=persona["code"],
        name=persona["name"],
    )
    reply_text = role_safe_reply(reply_text, persona["name"], persona["code"])

    now = utc_now()
    try:
        with db:
            user_cursor = db.execute(
                """
                INSERT INTO chat_history
                    (username, girl_name, girl_char, role, content, create_time)
                VALUES (?, ?, ?, 'user', ?, ?)
                """,
                (username, persona["name"], persona["label"], message, now),
            )
            assistant_cursor = db.execute(
                """
                INSERT INTO chat_history
                    (username, girl_name, girl_char, role, content, create_time)
                VALUES (?, ?, ?, 'assistant', ?, ?)
                """,
                (username, persona["name"], persona["label"], reply_text, now),
            )
    except sqlite3.DatabaseError:
        raise ApiError(
            "聊天记录暂时没有保存成功，请稍后再试。",
            code="HISTORY_SAVE_FAILED",
            status_code=500,
        )

    notice = None
    if mode == "fallback":
        notice = "模型服务暂不可用，这条回复来自本地角色引擎。"

    return success(
        {
            "user_message": {
                "id": user_cursor.lastrowid,
                "role": "user",
                "content": message,
                "create_time": now,
            },
            "assistant_message": {
                "id": assistant_cursor.lastrowid,
                "role": "assistant",
                "content": reply_text,
                "create_time": now,
            },
            "persona": {
                "girl_name": persona["name"],
                "girl_char": persona["label"],
                "personality": persona["code"],
            },
            "mode": mode,
            "notice": notice,
        },
        status=201,
    )
