@echo off
chcp 65001 >nul
cd /d "%~dp0.."
rem Сборка EXE-установщика: значки → Inno Setup → Zip\ClaudeOverlay-Setup-<версия>.exe
for /f %%v in ('.venv\Scripts\python.exe -c "import app; print(app.VERSION)"') do set VER=%%v
.venv\Scripts\python.exe setup\make_art.py
set ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
if not exist "%ISCC%" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
"%ISCC%" /Q /DAppVersion=%VER% setup\ClaudeOverlay.iss
if errorlevel 1 (echo Сборка не удалась & exit /b 1)
echo Готово: Zip\ClaudeOverlay-Setup-%VER%.exe
