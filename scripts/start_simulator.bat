@echo off
REM 一键启动 PC 模拟器(无板子时,先打通链路)
cd /d "%~dp0..\simulator"
echo.
echo === PC IMU Simulator ===
echo 默认地址 http://127.0.0.1:8000,可在命令行后追加参数,如:
echo   python send_sim.py --group G03 --hz 5
echo.
python send_sim.py %*
pause
