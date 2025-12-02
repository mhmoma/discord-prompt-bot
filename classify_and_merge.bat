@echo off
chcp 65001 >nul
echo ===================================
echo  词库分类与合并工具
echo ===================================
echo.

cd /d "%~dp0"

echo 正在运行分类和合并脚本...
echo 这可能需要几分钟时间，请耐心等待...
echo.

python classify_and_merge_lexicon.py

echo.
echo ===================================
echo  处理完成
echo ===================================
pause



