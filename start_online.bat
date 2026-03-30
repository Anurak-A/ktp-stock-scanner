@echo off
D:
cd \OneDrive\Desktop\Stocks
echo Starting KTP Stock Scanner...
start "" python app.py
timeout /t 3 /nobreak >nul
start "" ngrok http 1010
echo.
echo Server + ngrok started!
echo Check ngrok window for public URL.
pause
