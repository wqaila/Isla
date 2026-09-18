@echo off
REM ================================================================
REM   把本地提交推送到 GitHub
REM   仓库: https://github.com/wqaila/Isla
REM   前提: 本机能访问 GitHub(国内可能需要开代理/VPN)
REM ================================================================
cd /d "%~dp0.."

echo === 当前仓库状态 ===
git status --short
echo.
echo === 待推送的提交 ===
git log --oneline -5
echo.
echo === 远程地址 ===
git remote -v
echo.

echo === 开始推送 ===
git push -u origin main
echo.

echo ---------------------------------------------------------------
echo  如果上面出现以下字样,请把报错整段发给 AI 助手:
echo    - "rejected" / "non-fast-forward"  远程已有别的提交,需要先合并或覆盖
echo    - "Authentication failed"          需要登录 GitHub(建议用 Personal Access Token)
echo    - "Failed to connect" / "timed out"  网络不通,请开代理/VPN 后重试
echo ---------------------------------------------------------------
pause
