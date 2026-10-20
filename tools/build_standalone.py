#!/usr/bin/env python3
"""把单文件版模板、样式和逻辑打包成一个可双击打开的 HTML。

单文件版使用 standalone/index.template.html 作为模板，
与当前 Flask 账号登录版解耦，后续改登录功能不会影响离线版。

生成命令：
    python tools/build_standalone.py

输出：
    项目根目录/心屿.html
"""

from __future__ import annotations

import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "standalone" / "index.template.html"
BASE_CSS = ROOT / "static" / "css" / "style.css"
EXTRA_CSS = ROOT / "standalone" / "extra.css"
APP_JS = ROOT / "standalone" / "app.js"
SETTINGS_HTML = ROOT / "standalone" / "settings-dialog.html"
FAVICON = ROOT / "static" / "favicon.svg"
OUTPUT = ROOT / "心屿.html"

SETTINGS_ICON = """    <symbol id="icon-settings" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.5"/>
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
    </symbol>
"""

HEADER_TOOLS = """    <div class="header-tools">
      <div class="privacy-mark">
        <svg class="icon" aria-hidden="true"><use href="#icon-lock"></use></svg>
        <span>只属于你</span>
      </div>
      <button class="settings-mark" type="button" data-open-settings aria-label="打开模型设置" title="AI 设置">
        <svg class="icon" aria-hidden="true"><use href="#icon-settings"></use></svg>
      </button>
    </div>
"""

ASIDE_SETTINGS_BUTTON = """            <button class="aside-action is-settings" type="button" data-open-settings>
              <span>连接大模型</span>
              <svg class="icon" aria-hidden="true"><use href="#icon-settings"></use></svg>
            </button>
"""

MODE_BADGE = """              <button class="mode-badge" id="modeBadge" type="button" data-open-settings title="当前回复来源">
                <i aria-hidden="true"></i>
                <span id="modeBadgeText">本地体验</span>
              </button>"""


def must_replace(text: str, needle: str, replacement: str) -> str:
    if needle not in text:
        raise RuntimeError(f"模板缺少预期片段，无法打包：{needle[:80]!r}")
    return text.replace(needle, replacement, 1)


def build() -> Path:
    html = TEMPLATE.read_text(encoding="utf-8")
    base_css = BASE_CSS.read_text(encoding="utf-8")
    extra_css = EXTRA_CSS.read_text(encoding="utf-8")
    app_js = APP_JS.read_text(encoding="utf-8")
    settings_html = SETTINGS_HTML.read_text(encoding="utf-8")
    favicon_b64 = base64.b64encode(FAVICON.read_bytes()).decode("ascii")

    # 标题与 favicon：不再依赖 Flask 的 url_for。
    html = must_replace(
        html,
        "<title>心屿 · AI 女友</title>",
        "<title>心屿 · AI 女友（单文件版）</title>",
    )
    html = must_replace(
        html,
        """  <link rel="icon" href="{{ url_for('static', filename='favicon.svg') }}" type="image/svg+xml">""",
        f'  <link rel="icon" href="data:image/svg+xml;base64,{favicon_b64}" type="image/svg+xml">',
    )
    html = must_replace(
        html,
        """  <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">""",
        f"""  <style>
{base_css}

{extra_css}
  </style>""",
    )

    # 移除 Flask 版本的模块脚本，稍后注入单文件脚本。
    html = must_replace(
        html,
        """  <script type="module" src="{{ url_for('static', filename='js/app.js') }}"></script>\n""",
        "",
    )

    # 新增设置齿轮图标。
    html = must_replace(
        html,
        """    <symbol id="icon-chevron-down" viewBox="0 0 24 24">""",
        SETTINGS_ICON + """    <symbol id="icon-chevron-down" viewBox="0 0 24 24">""",
    )

    # 顶部：隐私标记 + 设置入口。
    html = must_replace(
        html,
        """    <div class="privacy-mark">
      <svg class="icon" aria-hidden="true"><use href="#icon-lock"></use></svg>
      <span>只属于你</span>
    </div>
""",
        HEADER_TOOLS,
    )

    # 侧栏设置入口。
    html = must_replace(
        html,
        """            <button class="aside-action" id="newChat" type="button">
              <span>重新开始对话</span>
              <svg class="icon" aria-hidden="true"><use href="#icon-refresh"></use></svg>
            </button>
          </div>
""",
        """            <button class="aside-action" id="newChat" type="button">
              <span>重新开始对话</span>
              <svg class="icon" aria-hidden="true"><use href="#icon-refresh"></use></svg>
            </button>
"""
        + ASIDE_SETTINGS_BUTTON
        + """          </div>
""",
    )

    # 模式徽标改为可点击的设置入口。
    html = must_replace(
        html,
        """              <span class="mode-badge" id="modeBadge" title="当前回复来源">
                <i aria-hidden="true"></i>
                <span id="modeBadgeText">正在连接</span>
              </span>""",
        MODE_BADGE,
    )

    # 单文件版文案：不再是 SQLite / 服务端数据库。
    html = must_replace(
        html,
        "对话会保存在本地 SQLite 中，下次推门回来，她还在。",
        "对话会保存在当前浏览器的 localStorage 中，下次推门回来，她还在。",
    )
    html = must_replace(
        html,
        "你的设置与聊天只保存在这台设备的本地数据库中。",
        "你的设置与聊天只保存在当前浏览器中，不会上传到任何服务器。",
    )

    # 注入模型设置弹窗。
    html = must_replace(
        html,
        """  <div class="toast-region" id="toastRegion" aria-live="polite" aria-atomic="false"></div>""",
        settings_html
        + """
  <div class="toast-region" id="toastRegion" aria-live="polite" aria-atomic="false"></div>""",
    )

    # 注入全部逻辑，最终文件不依赖任何本地或远程资源。
    html = must_replace(
        html,
        "</body>",
        f"""  <!-- 单文件版逻辑：打开即用，无需服务器 -->
  <script>
{app_js}
  </script>
</body>""",
    )

    leftover = [marker for marker in ("{{", "{%") if marker in html]
    if leftover:
        raise RuntimeError(f"打包结果仍包含 Jinja 模板标记：{leftover}")

    banner = (
        "<!--\n"
        "  心屿 · AI 女友（单文件离线版）\n"
        "  直接双击本文件即可使用，不需要安装 Flask、Node 或数据库。\n"
        "  默认本地体验模式；可在页面右上角 / 聊天侧栏配置 OpenAI 兼容接口。\n"
        "  由 tools/build_standalone.py 生成，请勿直接手改本文件。\n"
        "-->\n"
    )
    html = banner + html
    OUTPUT.write_text(html, encoding="utf-8")
    return OUTPUT


if __name__ == "__main__":
    path = build()
    size_kb = path.stat().st_size / 1024
    print(f"Built: {path} ({size_kb:.1f} KB)")
