@echo off
setlocal

REM 切换到 UTF-8 代码页以防止乱码
chcp 65001 > nul

REM 设置 Git 仓库地址和代理地址
set "REPO_URL=https://github.com/mhmoma/xiaoha.git"
set "PROXY_URL=http://127.0.0.1:18888"

echo "正在清理旧的仓库历史并重新上传到 %REPO_URL%..."

REM 强制删除旧的.git目录，清除历史记录
rmdir /s /q .git >nul 2>&1

REM 重新初始化 Git 仓库
git init
git branch -M main

REM 添加远程仓库 (先移除旧的，避免出错)
git remote remove origin >nul 2>&1
git remote add origin %REPO_URL%

REM 为启动脚本添加可执行权限 (Linux 环境需要)
git update-index --add --chmod=+x start.sh

REM 添加所有文件并提交
git add .
git commit -m "Final deployment push with all features"

REM 强制推送到远程仓库的 main 分支 (强制使用指定代理)
echo "正在推送到远程仓库 (将强制使用代理 %PROXY_URL%)..."
git -c http.proxy="%PROXY_URL%" -c https.proxy="%PROXY_URL%" push -u -f origin main

echo.
echo "***********************************************************"
echo "  所有更新已成功上传到你的 GitHub 仓库!  "
echo "***********************************************************"
echo.

pause
