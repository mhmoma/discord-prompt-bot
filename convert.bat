@echo off
chcp 65001 >nul
echo ===================================
echo  转换词库.json格式
echo ===================================
echo.

REM Change directory to the script's location
cd /d "%~dp0"

echo 正在运行转换脚本...
echo.

python convert_lexicon.py

echo.
echo ===================================
echo  转换完成
echo ===================================
pause



