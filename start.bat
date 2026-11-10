@echo off
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
