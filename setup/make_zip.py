# Собирает Zip/claude_overlay.zip: только исходники для друзей (без .venv, workspace, tests, документов для разработки).
import os
import sys
import zipfile

ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "Zip", "claude_overlay.zip")
FILES = ["overlay.py", "requirements.txt", "Установить.bat", "Удалить.bat", "start.bat", "README.md",
         "КАК ЗАПУСТИТЬ.txt", "Промпт для конспекта.txt"]
os.makedirs(os.path.dirname(OUT), exist_ok=True)
tmp = OUT + ".tmp"
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
    for f in FILES:
        z.write(os.path.join(ROOT, f), "claude_overlay/" + f)
    z.write(os.path.join(ROOT, "setup", "install.ps1"), "claude_overlay/setup/install.ps1")
    for name in sorted(os.listdir(os.path.join(ROOT, "app"))):
        p = os.path.join(ROOT, "app", name)
        if os.path.isfile(p) and name.endswith((".py", ".ico", ".png")):
            z.write(p, "claude_overlay/app/" + name)
os.replace(tmp, OUT)
with zipfile.ZipFile(OUT) as z:
    for i in z.infolist():
        print(f"{i.file_size:>8}  {i.filename}")
    print("проверка архива:", z.testzip() or "ок")
print("архив:", OUT, os.path.getsize(OUT), "байт")
