"""心屿 · AI 女友 —— Flask 应用入口。

启动：
    python app.py
默认地址：
    http://127.0.0.1:5000
"""

from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

import database
from config import Config
from errors import ApiError
from routes.api import bp as api_bp
from routes.auth import auth_bp


def create_app(test_config: dict | None = None) -> Flask:
    """应用工厂：便于测试时注入临时数据库与配置。"""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    # Flask 3 的 JSON 中文输出配置；同时保持 UTF-8 可读。
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    # 确保数据库目录存在，再执行建表脚本。
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    database.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)

    # ------------------------------------------------------------------
    # 页面
    # ------------------------------------------------------------------
    @app.get("/")
    def index():
        """整个前端只有这一份 HTML，登录、人设和聊天页面无刷新切换。"""
        return render_template("index.html")

    @app.get("/favicon.ico")
    def favicon():
        """补一个传统 favicon 路径，避免浏览器自动探测时产生 404。"""
        return app.send_static_file("favicon.svg")

    # ------------------------------------------------------------------
    # 统一异常处理
    # ------------------------------------------------------------------
    @app.errorhandler(ApiError)
    def handle_api_error(error: ApiError):
        return jsonify(error.to_dict()), error.status_code

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException):
        if request.path.startswith("/api/"):
            code = {
                400: "BAD_REQUEST",
                404: "NOT_FOUND",
                405: "METHOD_NOT_ALLOWED",
                413: "PAYLOAD_TOO_LARGE",
            }.get(error.code or 500, "HTTP_ERROR")
            message = {
                404: "没有找到这个接口。",
                405: "这个接口不支持当前请求方式。",
                413: "请求内容太大了。",
            }.get(error.code or 500, error.description or "请求处理失败。")
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": {"code": code, "message": message},
                    }
                ),
                error.code or 500,
            )
        return error

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception):
        # 只记录异常栈，绝不把内部细节返回给浏览器。
        app.logger.exception("未处理异常: %s", error)
        if request.path.startswith("/api/"):
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": {
                            "code": "INTERNAL_ERROR",
                            "message": "服务器刚刚走神了，请稍后再试。",
                        },
                    }
                ),
                500,
            )
        return "服务器暂时开小差了，请稍后刷新页面。", 500

    # ------------------------------------------------------------------
    # 安全响应头
    # ------------------------------------------------------------------
    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        # 允许页面内的受控内联样式（动态角色主题色），脚本仅允许同源加载。
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "frame-ancestors 'none'",
        )
        if request.path.startswith("/api/") or request.path == "/":
            response.headers["Cache-Control"] = "no-store"
        return response

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # 使用纯 ASCII 标记，避免 Windows 终端默认 GBK 编码打印失败。
    print()
    print("  [Heart Island] AI Girlfriend")
    print(f"  -> http://{app.config['HOST']}:{app.config['PORT']}")
    print(
        "  -> Reply source: "
        + (
            "Kimi " + app.config["KIMI_MODEL"]
            if app.config.get("KIMI_API_KEY")
            else "local experience mode (KIMI_API_KEY is empty)"
        )
    )
    print()
    app.run(
        host=app.config["HOST"],
        port=app.config["PORT"],
        debug=app.config["DEBUG"],
        threaded=True,
        use_reloader=False,
    )
