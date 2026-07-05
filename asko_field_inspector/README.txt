
ASKO2 Field Inspector

Назначение:
Приложение открывает Chrome на https://asko2.novelty.kz/login.html.
Вы вручную вводите логин/пароль и переходите на нужную форму.
После этого приложение сохраняет скриншот и список элементов страницы.

Что сохраняется:
- screenshot_YYYYMMDD_HHMMSS.png
- fields_YYYYMMDD_HHMMSS.json
- fields_YYYYMMDD_HHMMSS.txt

Как запустить из исходников:
1. Установить Python 3.11 или 3.12.
2. В папке проекта выполнить:
   pip install -r requirements.txt
   python asko_field_inspector.py

Как собрать exe:
1. В папке проекта выполнить:
   build_exe.bat
2. Готовый файл будет здесь:
   dist\ASKO2_Field_Inspector.exe

Важно:
- Приложение не сохраняет пароль. password-поля маскируются.
- Chrome открывается через Selenium в отдельном профиле chrome_profile_asko2.
- Если ChromeDriver не найден, Selenium Manager сам попробует подобрать драйвер под установленный Chrome.
