@echo off
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
