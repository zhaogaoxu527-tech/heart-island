#!/usr/bin/env bash
# 心屿 · AI 女友 —— macOS / Linux 一键启动
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "未找到 python3，请先安装 Python 3.10 或更高版本。"
  exit 1
fi

if [ ! -d ".venv" ] || [ ! -x ".venv/bin/python" ]; then
  echo "[1/4] 创建虚拟环境 .venv ..."
  "$PYTHON_BIN" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "[2/4] 安装 / 检查依赖 ..."
python -m pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  echo "[3/4] 生成默认配置 .env ..."
  cp .env.example .env
else
  echo "[3/4] 已存在 .env，跳过。"
fi

echo "[4/4] 启动心屿：http://127.0.0.1:5000"
echo "未配置 KIMI_API_KEY 时自动使用本地体验模式，Ctrl+C 停止。"
python app.py
