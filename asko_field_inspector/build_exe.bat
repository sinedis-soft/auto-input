@echo off
chcp 65001 > nul
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m PyInstaller --onefile --windowed --name ASKO2_Field_Inspector asko_field_inspector.py
echo.
echo Готово. EXE находится в папке dist
pause
