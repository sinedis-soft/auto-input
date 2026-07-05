@echo off
setlocal

cd /d "%~dp0"

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --name BitrixPolicyAutomationHub ^
  --collect-all selenium ^
  --collect-all tzdata ^
  --hidden-import asko_bitrix_filler ^
  --hidden-import asko_bitrix_filler.asko_bitrix_filler ^
  --hidden-import selenium.webdriver.chrome.webdriver ^
  --hidden-import selenium.webdriver.chrome.options ^
  --hidden-import selenium.webdriver.chrome.service ^
  --hidden-import selenium.webdriver.chrome.remote_connection ^
  pyside_app_launcher.py

endlocal
