"""注册 / 登录 / 退出与会话鉴权。

安全约定：
- 密码只保存 Werkzeug 生成的不可逆哈希；
- 登录成功后服务端 session 只保存 user_id / username；
- 所有聊天接口都通过 @login_required 从服务端会话取用户名，
  前端无法伪造 username 读取别人的记录。
"""

from __future__ import annotations

import re
import sqlite3
from functools import wraps
from typing import Any, Callable, TypeVar

from flask import Blueprint, current_app, g, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

from database import get_db
from errors import ApiError

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

F = TypeVar("F", bound=Callable[..., Any])

USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fff]+$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def serialize_user(row: sqlite3.Row) -> dict[str, Any]:
    """永远不要返回 password 字段。"""
    return {"id": row["id"], "username": row["username"], "email": row["email"]}


def require_json() -> dict[str, Any]:
    from flask import request

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(
            "请求格式不正确，请使用 JSON 提交。",
            code="INVALID_JSON",
            status_code=400,
        )
    return data


def login_required(view: F) -> F:
    """校验服务端会话，并把当前用户放进 g.current_user。"""

    @wraps(view)
    def wrapped(*args, **kwargs):
        user_id = session.get("user_id")
        username = session.get("username")
        if not user_id or not username:
            raise ApiError(
                "请先登录，才能进入她的世界。",
                code="AUTH_REQUIRED",
                status_code=401,
            )

        db = get_db()
        user = db.execute(
            'SELECT id, username, email FROM "user" WHERE id = ? AND username = ?',
            (user_id, username),
        ).fetchone()
        if user is None:
            session.clear()
            raise ApiError(
                "登录状态已失效，请重新登录。",
                code="AUTH_REQUIRED",
                status_code=401,
            )

        g.current_user = user
        return view(*args, **kwargs)

    return wrapped  # type: ignore[return-value]


def _validate_username(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ApiError("请输入用户名。", code="VALIDATION_ERROR", status_code=422)
    username = raw.strip()
    minimum = current_app.config["USERNAME_MIN_LENGTH"]
    maximum = current_app.config["USERNAME_MAX_LENGTH"]
    if not (minimum <= len(username) <= maximum):
        raise ApiError(
            f"用户名需要 {minimum}–{maximum} 个字符。",
            code="VALIDATION_ERROR",
            status_code=422,
        )
    if not USERNAME_RE.fullmatch(username):
        raise ApiError(
            "用户名只能包含中文、字母、数字和下划线。",
            code="VALIDATION_ERROR",
            status_code=422,
        )
    return username


def _validate_email(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ApiError("请输入邮箱。", code="VALIDATION_ERROR", status_code=422)
    email = raw.strip().lower()
    if len(email) > 120 or not EMAIL_RE.fullmatch(email):
        raise ApiError(
            "请输入有效的邮箱地址。",
            code="VALIDATION_ERROR",
            status_code=422,
        )
    return email


def _validate_password(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ApiError("请输入密码。", code="VALIDATION_ERROR", status_code=422)
    minimum = current_app.config["PASSWORD_MIN_LENGTH"]
    maximum = current_app.config["PASSWORD_MAX_LENGTH"]
    if len(raw) < minimum:
        raise ApiError(
            f"密码至少需要 {minimum} 位。",
            code="VALIDATION_ERROR",
            status_code=422,
        )
    if len(raw) > maximum:
        raise ApiError(
            f"密码最多 {maximum} 位。",
            code="VALIDATION_ERROR",
            status_code=422,
        )
    return raw


@auth_bp.post("/register")
def register():
    """创建用户；密码以不可逆哈希形式写入 SQLite。"""
    payload = require_json()
    username = _validate_username(payload.get("username"))
    email = _validate_email(payload.get("email"))
    password = _validate_password(payload.get("password"))

    db = get_db()
    duplicate = db.execute(
        'SELECT username, email FROM "user" WHERE username = ? OR email = ?',
        (username, email),
    ).fetchone()
    if duplicate is not None:
        if duplicate["username"].lower() == username.lower():
            raise ApiError(
                "这个用户名已经被使用了，换一个吧。",
                code="USERNAME_EXISTS",
                status_code=409,
            )
        raise ApiError(
            "这个邮箱已经注册过了，可以直接登录。",
            code="EMAIL_EXISTS",
            status_code=409,
        )

    password_hash = generate_password_hash(password)
    try:
        with db:
            cursor = db.execute(
                'INSERT INTO "user" (username, password, email) VALUES (?, ?, ?)',
                (username, password_hash, email),
            )
    except sqlite3.IntegrityError:
        raise ApiError(
            "用户名或邮箱已被占用，请换一个。",
            code="USER_EXISTS",
            status_code=409,
        )

    row = db.execute(
        'SELECT id, username, email FROM "user" WHERE id = ?',
        (cursor.lastrowid,),
    ).fetchone()
    return jsonify({"ok": True, "data": {"user": serialize_user(row)}}), 201


@auth_bp.post("/login")
def login():
    """校验用户名和密码，成功后写入服务端会话。"""
    payload = require_json()
    username = payload.get("username")
    password = payload.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise ApiError(
            "请输入用户名和密码。",
            code="VALIDATION_ERROR",
            status_code=422,
        )

    db = get_db()
    user = db.execute(
        'SELECT id, username, password, email FROM "user" WHERE username = ?',
        (username.strip(),),
    ).fetchone()
    if user is None or not check_password_hash(user["password"], password):
        raise ApiError(
            "用户名或密码不正确。",
            code="INVALID_CREDENTIALS",
            status_code=401,
        )

    session.clear()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session.permanent = True

    return jsonify({"ok": True, "data": {"user": serialize_user(user)}})


@auth_bp.post("/logout")
def logout():
    """清空会话。"""
    session.clear()
    return jsonify({"ok": True, "data": {"logged_out": True}})


@auth_bp.get("/me")
def me():
    """前端启动时用于判断登录状态；未登录返回 authenticated=false。"""
    user_id = session.get("user_id")
    username = session.get("username")
    if not user_id or not username:
        return jsonify(
            {
                "ok": True,
                "data": {"authenticated": False, "user": None},
            }
        )

    row = get_db().execute(
        'SELECT id, username, email FROM "user" WHERE id = ? AND username = ?',
        (user_id, username),
    ).fetchone()
    if row is None:
        session.clear()
        return jsonify(
            {
                "ok": True,
                "data": {"authenticated": False, "user": None},
            }
        )
    return jsonify(
        {
            "ok": True,
            "data": {"authenticated": True, "user": serialize_user(row)},
        }
    )
