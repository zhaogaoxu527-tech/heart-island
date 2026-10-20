@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo.
echo   [Heart Island] AI Girlfriend
echo   ------------------------------------
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo   [!] 未检测到 Python。请先安装 Python 3.10 或更高版本。
    echo       下载地址：https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

rem 已存在但缺少 pip 的半成品虚拟环境，删除后重建。
if exist ".venv\Scripts\python.exe" if not exist ".venv\Scripts\pip.exe" (
    echo   [i] 检测到不完整的虚拟环境，正在重建...
    rmdir /s /q ".venv" 2>nul
)

if not exist ".venv\Scripts\python.exe" (
    echo   [1/4] 正在创建虚拟环境 .venv ...
    python -m venv .venv
    if errorlevel 1 goto :failed
)

call ".venv\Scripts\activate.bat"

echo   [2/4] 正在检查依赖 ...
python -m pip install -q -r requirements.txt
if errorlevel 1 goto :failed

if not exist ".env" (
    echo   [3/4] 正在生成默认配置 .env ...
    copy /Y ".env.example" ".env" >nul
) else (
    echo   [3/4] 已检测到 .env，跳过配置复制。
)

echo   [4/4] 正在启动心屿 ...
echo.
echo   浏览器打开：http://127.0.0.1:5000
echo   未配置 KIMI_API_KEY 时会自动使用本地体验模式。
echo   按 Ctrl+C 可停止服务。
echo.
python app.py
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo   [!] 启动失败，请检查上方的错误信息。
echo       常见原因：网络无法安装依赖、端口被占用、Python 版本低于 3.10。
echo.
pause
exit /b 1
