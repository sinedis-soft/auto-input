
# WARTA Robot App v2

GUI-приложение для WARTA OC graniczne.

Что есть в этой версии:
- EXE-сборка через PyInstaller.
- Окно настроек: WARTA login, WARTA password, Bitrix24 webhook, WARTA URL.
- Главное окно: поле ссылки на сделку Bitrix24 и кнопка `Начать / Продолжить`.
- Браузер не закрывается после заполнения данных.
- Логика пауз: программа делает автоматический этап, затем ждёт, пока оператор руками подтвердит/выберет данные и снова нажмёт кнопку.
- Отдельный режим снимков DOM/PNG/TXT для уточнения селекторов.

## Безопасность

Пароль WARTA и webhook Bitrix24 сохраняются локально в файле `settings.json`.

Это удобно для MVP, но не идеально с точки зрения безопасности. На рабочем внедрении лучше заменить хранение секретов на Windows Credential Manager.

Не отправляйте `settings.json` никому.

Если пароль или webhook уже были переданы в чат, их нужно заменить.

## Установка для разработки

```bat
cd /d G:\programming
powershell Expand-Archive -Path C:\Users\%USERNAME%\Downloads\warta_robot_app_v2.zip -DestinationPath G:\programming -Force
cd /d G:\programming\warta_robot_app_v2
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
python app.py
```

## Сборка EXE

```bat
build_exe.bat
```

Файл будет здесь:

```text
dist\WARTA Robot.exe
```

## Как работать

1. Откройте приложение.
2. Нажмите `Настройки`.
3. Введите:
   - WARTA login;
   - WARTA password;
   - Bitrix24 webhook;
   - WARTA URL.
4. Сохраните.
5. Вставьте ссылку на сделку Bitrix24.
6. Нажмите `Начать / Продолжить`.
7. Программа откроет WARTA и попробует войти.
8. 2FA вводите руками в браузере.
9. После появления главной страницы WARTA снова нажмите `Начать / Продолжить`.
10. Программа идёт по OC graniczne, вводит номер и VIN, нажимает `SPRAWDŹ`.
11. Потом заполняет:
    - Rodzaj pojazdu = Samochód osobowy, если в Bitrix тип ТС Passenger car;
    - Data pierwszej rejestracji = 10-02-[год];
    - Marka = первые 3 символа из поля Marka i model pojazdu;
    - Rok produkcji = год.
12. Затем программа ждёт, пока оператор выберет:
    - Marka из подсказки;
    - Paliwo;
    - Model;
    - Typ / Wersja pojazdu według Info-Ekspert.
13. После ручного выбора снова нажмите кнопку `Начать / Продолжить`.

## Важно

После VIN часть селекторов WARTA ещё может потребовать уточнения. Если приложение не находит поле, используйте кнопку `Снимок страницы`, пришлите JSON/TXT, и selector будет добавлен точно.
