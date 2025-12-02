@echo off
chcp 65001 >nul
echo ===================================
echo  合并知识库文件
echo ===================================
echo.

cd /d "%~dp0"

echo 正在运行合并脚本...
echo.

python merge_knowledge_base.py

echo.
echo ===================================
echo  合并完成
echo ===================================
pause



