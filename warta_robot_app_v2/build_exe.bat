@echo off
cd /d %~dp0

if not exist .venv (
    python -m venv .venv
)

call .venv\Scripts\activate

pip install -r requirements.txt
python -m playwright install chromium

pyinstaller ^
  --onefile ^
  --name "WARTA Robot" ^
  --clean ^
  --noconsole ^
  app.py

echo.
echo EXE created: dist\WARTA Robot.exe
echo.
pause
