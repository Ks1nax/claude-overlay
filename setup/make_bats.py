# Пишет .bat файлы проекта в UTF-8 без BOM и с переводами строк CRLF (так их правильно читает cmd).
import os
import sys

ROOT = sys.argv[1]

INSTALL = r'''@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Установка Claude Overlay
if not exist "%~dp0overlay.py" (
    echo.
    echo  Сначала распакуй архив: правой кнопкой по архиву — «Извлечь всё»,
    echo  потом открой распакованную папку и запусти «Установить.bat» оттуда.
    pause
    exit /b 1
)
rem Вся установка — в setup\install.ps1 (PowerShell нормально работает с русскими путями и находит Python через реестр)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\install.ps1" -AppDir "%~dp0."
if errorlevel 1 exit /b 1
echo.
echo  Открываю мастер настройки... Это окно закроется само.
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0overlay.py" --wizard
timeout /t 3 >nul
exit /b 0
'''
UNINSTALL = r'''@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title Удаление Claude Overlay
echo.
echo  ============================================================
echo    Claude Overlay — удаление
echo  ============================================================
echo    Уберу ярлыки и окружение программы (.venv).
echo    Скачанные модели и материалы — по твоему выбору ниже.
echo.
set "QUIET="
if /i "%~1"=="/quiet" set "QUIET=1"
if defined QUIET goto go
choice /c 10 /n /m "  Продолжить? [1 — да, 0 — нет]: "
if errorlevel 2 exit /b 0
:go

echo  Закрываю оверлей, если он запущен...
powershell -NoProfile -Command "$d = '%~dp0'.TrimEnd('\'); Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine -like ('*' + $d + '*overlay.py*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
timeout /t 2 >nul

echo  Убираю ярлыки (рабочий стол, «Пуск», автозагрузка)...
powershell -NoProfile -Command "$d = '%~dp0'.TrimEnd('\'); $ws = New-Object -ComObject WScript.Shell; foreach ($f in 'Desktop','Programs','Startup') { $p = Join-Path ([Environment]::GetFolderPath($f)) 'Claude Overlay.lnk'; if (Test-Path $p) { $s = $ws.CreateShortcut($p); if (($s.Arguments + ' ' + $s.TargetPath) -like ('*' + $d + '*')) { Remove-Item $p -Force; Write-Host ('   убран: ' + $p) } else { Write-Host ('   оставлен (ведёт в другую папку): ' + $p) } } }"

if exist ".venv" (
    echo  Удаляю окружение .venv ^(библиотеки, в том числе для видеокарты^)...
    rmdir /s /q ".venv"
)

if defined QUIET goto done
echo.
choice /c 10 /n /m "  Удалить скачанные модели распознавания речи (до 6 ГБ)? [1 — да, 0 — нет]: "
if errorlevel 2 goto keep_models
powershell -NoProfile -Command "$h = if ($env:HF_HUB_CACHE) { $env:HF_HUB_CACHE } elseif ($env:HF_HOME) { Join-Path $env:HF_HOME 'hub' } else { Join-Path $env:USERPROFILE '.cache\huggingface\hub' }; foreach ($n in 'models--Systran--faster-whisper-tiny','models--Systran--faster-whisper-base','models--Systran--faster-whisper-small','models--Systran--faster-whisper-medium','models--Systran--faster-whisper-large-v3','models--mobiuslabsgmbh--faster-whisper-large-v3-turbo','models--Systran--faster-distil-whisper-large-v3') { $p = Join-Path $h $n; if (Test-Path $p) { Remove-Item $p -Recurse -Force; Write-Host ('   удалена: ' + $n) } }"
:keep_models

echo.
choice /c 10 /n /m "  Удалить материалы, настройки и журнал (папка workspace)? [1 — да, 0 — нет]: "
if errorlevel 2 goto keep_ws
if exist "workspace" rmdir /s /q "workspace"
echo   папка workspace удалена
:keep_ws

:done
echo.
echo  Готово. Саму папку программы можно удалить вручную.
if not defined QUIET pause
'''

START = r'''@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Запуск С КОНСОЛЬЮ — для отладки (видно всё, что программа пишет).
rem Обычный запуск — ярлык «Claude Overlay» (без консоли). Установка — «Установить.bat».

if not exist ".venv\Scripts\python.exe" (
    echo Программа ещё не установлена — запусти «Установить.bat».
    pause
    exit /b 1
)

rem докачать библиотеки, если после обновления оверлея добавились новые
".venv\Scripts\python.exe" -c "import faster_whisper, sounddevice, mss, PIL, pynput, matplotlib, pypdf, webview, pystray" 2>nul
if errorlevel 1 (
    echo Ставлю недостающие библиотеки...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

rem видеокарта NVIDIA: один раз докачать библиотеки CUDA и проверить (если нет — распознавание на процессоре)
".venv\Scripts\python.exe" overlay.py --setup-gpu

".venv\Scripts\python.exe" overlay.py %*
if errorlevel 1 pause
'''


def write(name, text):
    data = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
    with open(os.path.join(ROOT, name), "wb") as f:
        f.write(data)
    print("записан", name, len(data), "байт")


write("Установить.bat", INSTALL)
write("Удалить.bat", UNINSTALL)
write("start.bat", START)
