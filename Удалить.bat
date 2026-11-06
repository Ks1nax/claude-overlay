@echo off
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
