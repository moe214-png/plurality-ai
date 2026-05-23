@echo off
chcp 65001 >nul
set PYTHONUTF8=1
title 多 AI 对话控制台
cd /d "%~dp0"
echo 启动多 AI 对话控制台...
echo.
set "PANEL_PYTHON=D:\python\python.exe"
if exist "%PANEL_PYTHON%" (
  "%PANEL_PYTHON%" panel.py
) else (
  python panel.py
)
pause
