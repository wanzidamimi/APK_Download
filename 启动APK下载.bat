@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 应用宝 APK 下载器
echo 正在启动服务 http://127.0.0.1:8899 ...
start "" /min powershell -NoProfile -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8899'"
python -m uvicorn app:app --host 127.0.0.1 --port 8899
pause
