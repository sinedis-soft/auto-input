@echo off
chcp 65001 > nul
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m PyInstaller --onefile --windowed --name ASKO_Bitrix_Filler asko_bitrix_filler.py
echo.
echo Готово. EXE находится в папке dist
pause
