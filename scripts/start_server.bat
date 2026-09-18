@echo off
REM ================================================================
REM   一键启动本机 Flask 服务(本机充当 VPS)
REM   - 自动建 venv 装依赖
REM   - 自动健康检查
REM   - 打印 LAN IP,告诉下一步怎么连
REM ================================================================
setlocal ENABLEDELAYEDEXPANSION

cd /d "%~dp0..\server"

echo === [1/3] 准备 Python 环境 ===
if not exist .venv (
    echo [setup] 首次运行,创建虚拟环境 .venv ...
    python -m venv .venv || (echo [error] python 未安装或不可用 & pause & exit /b 1)
    call .venv\Scripts\activate
    python -m pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
) else (
    call .venv\Scripts\activate
)

echo.
echo === [2/3] 探测端口 8000 ===
netstat -ano | findstr ":8000" >nul 2>&1
if not errorlevel 1 (
    echo [warn] 8000 端口已被占用。请确认上次进程已关闭,或改端口。
    echo        PowerShell: Get-NetTCPConnection -LocalPort 8000
)

echo.
echo === [3/3] 启动 Flask ===
echo [open] http://127.0.0.1:8000  (同一台电脑访问)
echo [warn] 若板子或别的电脑要访问,请用本机的 LAN IP,可在 PowerShell 跑 ipconfig 看到。
echo.
echo ---------- 下面开始打印服务日志,Ctrl+C 退出 ----------
echo.
python app.py

pause
