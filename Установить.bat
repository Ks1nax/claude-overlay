@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Установка Claude Overlay
if not exist "%~dp0overlay.py" (
    echo.
    echo  Сначала распакуй архив: правой кнопкой по архиву — «Извлечь всё»,
    echo  потом открой распакованную папку и запусти «Установить.bat» оттуда.
    pause
    exit /b 1
)

echo.
echo  ============================================================
echo    Claude Overlay — установка
echo  ============================================================
echo    Сейчас поставлю всё нужное. Окно закроется само, и откроется
echo    мастер настройки. Повторный запуск ничего не ломает —
echo    только доделывает то, чего не хватает.
echo.

rem ---------- 1. Python 3.10+ ----------
set "PYEXE="
call :find_python
if not defined PYEXE (
    echo  [1/3] Python не найден — ставлю Python 3.12 ^(официальный, с python.org^)...
    where winget >nul 2>nul
    if not errorlevel 1 (
        winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements --override "/passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_tcltk=1 Include_pip=1"
        call :find_python
    )
)
if not defined PYEXE (
    echo  winget не помог — качаю установщик Python с python.org ^(~25 МБ^)...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='Continue'; Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile \"$env:TEMP\python-3.12.10-amd64.exe\""
    if exist "%TEMP%\python-3.12.10-amd64.exe" (
        echo  Устанавливаю Python — подожди минуту...
        "%TEMP%\python-3.12.10-amd64.exe" /passive InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_tcltk=1 Include_pip=1
        call :find_python
    )
)
if not defined PYEXE (
    echo.
    echo  [ОШИБКА] Не получилось установить Python.
    echo  Поставь его вручную: https://www.python.org/downloads/  ^(версия 3.12,
    echo  галочка «Add python.exe to PATH»^), потом снова запусти «Установить.bat».
    pause
    exit /b 1
)
echo  [1/3] Python: !PYEXE!

rem ---------- 2. окружение .venv и библиотеки ----------
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import sys, tkinter" >nul 2>nul
    if errorlevel 1 (
        echo  Старое окружение .venv сломано ^(например, удалили Python^) — откладываю его и создаю заново...
        for /f %%t in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "STAMP=%%t"
        ren ".venv" ".venv_old_!STAMP!"
    )
)
if not exist ".venv\Scripts\python.exe" (
    echo  [2/3] Создаю окружение для программы ^(.venv^)...
    "!PYEXE!" -m venv .venv
    if errorlevel 1 (
        echo  [ОШИБКА] Не получилось создать .venv. Подробности выше.
        pause
        exit /b 1
    )
)
echo  [2/3] Ставлю библиотеки ^(первый раз ~1-2 ГБ, несколько минут^)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --upgrade pip
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo.
    echo  [ОШИБКА] Библиотеки не поставились. Чаще всего — нет интернета или его режет
    echo  антивирус/прокси. Проверь интернет и запусти «Установить.bat» ещё раз:
    echo  он продолжит с того места, где остановился.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import faster_whisper, sounddevice, mss, PIL, pynput, matplotlib, pypdf, tkinterdnd2, pystray, numpy" 2>nul
if errorlevel 1 (
    echo  [ОШИБКА] Библиотеки поставились не все — запусти «Установить.bat» ещё раз.
    pause
    exit /b 1
)

rem ---------- 3. мастер настройки (окно) ----------
echo  [3/3] Открываю мастер настройки...
start "" ".venv\Scripts\pythonw.exe" "%~dp0overlay.py" --wizard
echo.
echo  Готово — дальше в окне мастера. Это окно закроется само.
timeout /t 4 >nul
exit /b 0


rem ======== поиск Python 3.10+ (с tkinter) ========
:find_python
set "PYEXE="
for %%v in (3.12 3.13 3.11 3.14 3.10) do (
    if not defined PYEXE call :try_py "py" "-%%v"
)
if not defined PYEXE call :try_py "py" "-3"
for %%d in ("%LOCALAPPDATA%\Programs\Python\Python312" "%LOCALAPPDATA%\Programs\Python\Python313" "%LOCALAPPDATA%\Programs\Python\Python311" "%LOCALAPPDATA%\Programs\Python\Python314" "%LOCALAPPDATA%\Programs\Python\Python310" "%ProgramFiles%\Python312" "%ProgramFiles%\Python313" "%ProgramFiles%\Python311" "%ProgramFiles%\Python314" "%ProgramFiles%\Python310" "C:\Python312" "C:\Python313" "C:\Python311" "C:\Python314" "C:\Python310") do (
    if not defined PYEXE if exist "%%~d\python.exe" call :try_py "%%~d\python.exe" ""
)
if not defined PYEXE call :try_py "python" ""
exit /b 0

:try_py
set "OUT="
for /f "usebackq delims=" %%p in (`call "%~1" %~2 -c "import sys, tkinter; print(sys.executable if (3,10) <= sys.version_info[:2] < (3,15) else str())" 2^>nul`) do set "OUT=%%p"
if defined OUT if exist "!OUT!" set "PYEXE=!OUT!"
exit /b 0
