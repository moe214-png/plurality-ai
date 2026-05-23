@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo 启动四模型 API 对话
echo.
echo 示例:
echo python api_dialogue.py --reset --rounds 1 --prompt "讨论如何改进这个项目"
echo.
cmd /k
