@echo off
echo ===================================
echo  Starting Discord Bot...
echo ===================================
echo.

REM Change directory to the script's location
d:
cd /d "%~dp0"

echo Activating virtual environment and running the bot...
echo If the bot fails to start, check your .env file and network connection.
echo.

.\.venv\Scripts\python.exe bot.py

echo.
echo ===================================
echo  Bot script has finished or been stopped.
echo ===================================
pause
