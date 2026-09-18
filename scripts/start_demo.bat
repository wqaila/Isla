@echo off
REM ================================================================
REM   一键"无板子先打通链路":同时启动 Flask 服务 + PC 模拟器
REM   - 两个独立窗口,互不干扰
REM   - Ctrl+C 各自退;关窗口即可
REM ================================================================
setlocal

set ROOT=%~dp0..
echo === ROOT=%ROOT% ===

REM --- 在新窗口起服务 ---
start "IMU-Flask" cmd /k "cd /d %ROOT%\server && call .venv\Scripts\activate && python app.py"

REM --- 稍等服务起来,再起模拟器(避免前几条请求 503) ---
echo [wait] 等待服务就绪 ...
:waitloop
timeout /t 1 /nobreak >nul
powershell -NoProfile -Command "$r = try { Invoke-WebRequest -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2 } catch { $null }; if ($r -and $r.StatusCode -eq 200) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 goto waitloop

echo [ok] 服务已就绪,启动模拟器 ...

REM --- 在新窗口起模拟器 ---
start "IMU-Simulator" cmd /k "cd /d %ROOT%\simulator && python send_sim.py --server http://127.0.0.1:8000 --group G03 --device sim-pc-01 --hz 2"

echo.
echo === 完成 ===
echo 浏览器打开:  http://127.0.0.1:8000/
echo Group ID:     G03
echo.
echo 关掉任一窗口 = 停止那条链路;两个都关 = 全部停止。
echo.
pause
