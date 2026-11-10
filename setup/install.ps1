# Установка всего, что нужно Claude Overlay: Python 3.10-3.14 (с tcl/tk), окружение .venv, библиотеки.
# Её запускают и EXE-установщик (Inno Setup), и Установить.bat. Повторный запуск ничего не ломает — только доделывает.
#
# Для EXE-установщика в стандартный вывод идут служебные строки «@@ШАГ аргумент» (латиницей — без проблем с
# кодировкой), а русский текст для человека — через Write-Host.
#
# Почему не простой .bat (баг от друга): Python 3.12 у него был установлен, но .bat его не нашёл — путь к Python
# с русскими буквами (имя пользователя) приходил из Python в другой кодировке, и проверка «файл есть» не срабатывала;
# либо Python стоял без tcl/tk. Здесь Python ищется через реестр Windows и пути не проходят через cmd.
param(
    [string]$AppDir = "",
    [switch]$NoPause,
    [switch]$ListOnly,      # только показать найденные Python (диагностика), ничего не ставить
    [switch]$ForceOwnPython # не брать найденные Python, поставить отдельный (если с найденными что-то не так)
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # большая синяя полоса «Writing web request» больше не появляется
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
if (-not $AppDir) { $AppDir = Split-Path -Parent $PSScriptRoot }
$AppDir = (Resolve-Path -LiteralPath $AppDir).Path
$Venv = Join-Path $AppDir ".venv"
$VPy = Join-Path $Venv "Scripts\python.exe"

function Emit([string]$key, [string]$arg = "") { [Console]::Out.WriteLine("@@$key $arg"); [Console]::Out.Flush() }
function Say([string]$text, [string]$color = "Gray") { Write-Host $text -ForegroundColor $color }

# ---------------------------------------------------------------- поиск Python

function Test-Python([string]$exe) {
    if (-not $exe -or -not (Test-Path -LiteralPath $exe)) { return $null }
    if ($exe -like "*\WindowsApps\*") { return $null }   # заглушка Microsoft Store, а не Python
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try {
        # вывод читаем целиком: «| Select-Object -First 1» обрывает программу, и она возвращает код -1
        $ver = @(& $exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null)
        if ($LASTEXITCODE -ne 0 -or $ver.Count -eq 0) { return $null }
        $ver = $ver[0]
        & $exe -c "import tkinter, venv" 2>$null | Out-Null
        $tk = ($LASTEXITCODE -eq 0)
    } catch { return $null } finally { $ErrorActionPreference = $old }
    $v = [version]("$ver".Trim())
    if ($v -lt [version]"3.10" -or $v -ge [version]"3.15") { return $null }
    return [pscustomobject]@{ Exe = $exe; Ver = $v; Tk = $tk }
}

function Find-Pythons {
    $paths = New-Object System.Collections.Generic.List[string]
    # 1) реестр (так Python регистрирует себя установщик python.org, winget, Astral и др.)
    foreach ($root in @("HKCU:\Software\Python", "HKLM:\Software\Python", "HKLM:\Software\WOW6432Node\Python")) {
        if (-not (Test-Path $root)) { continue }
        foreach ($company in Get-ChildItem $root -ErrorAction SilentlyContinue) {
            foreach ($tag in Get-ChildItem $company.PSPath -ErrorAction SilentlyContinue) {
                $ip = Join-Path $tag.PSPath "InstallPath"
                if (-not (Test-Path $ip)) { continue }
                $k = Get-ItemProperty $ip -ErrorAction SilentlyContinue
                if ($k.ExecutablePath) { $paths.Add($k.ExecutablePath) }
                if ($k.'(default)') { $paths.Add((Join-Path $k.'(default)' "python.exe")) }
            }
        }
    }
    # 2) лаунчер py
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        foreach ($line in (& $py.Source -0p 2>$null)) {
            if ($line -match '([A-Za-z]:\\.+python\.exe)\s*$') { $paths.Add($Matches[1]) }
        }
        $ErrorActionPreference = $old
    }
    # 3) привычные папки и PATH
    foreach ($v in "312", "313", "311", "314", "310") {
        $paths.Add("$env:LOCALAPPDATA\Programs\Python\Python$v\python.exe")
        $paths.Add("$env:ProgramFiles\Python$v\python.exe")
        $paths.Add("C:\Python$v\python.exe")
    }
    foreach ($c in (Get-Command python -All -ErrorAction SilentlyContinue)) { $paths.Add($c.Source) }
    $seen = @{}; $found = @()
    foreach ($p in $paths) {
        $key = $p.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        $r = Test-Python $p
        if ($r) { $found += $r }
    }
    return $found
}

function Pick-Python($found) {
    $good = @($found | Where-Object { $_.Tk })
    foreach ($want in "3.12", "3.13", "3.11", "3.14", "3.10") {
        $m = $good | Where-Object { "$($_.Ver.Major).$($_.Ver.Minor)" -eq $want } | Select-Object -First 1
        if ($m) { return $m }
    }
    return $null
}

# ---------------------------------------------------------------- загрузка с понятным прогрессом

function Download([string]$url, [string]$dest) {
    $req = [Net.HttpWebRequest]::Create($url)
    $req.UserAgent = "ClaudeOverlaySetup"
    $resp = $req.GetResponse()
    $total = $resp.ContentLength
    $in = $resp.GetResponseStream()
    $out = [IO.File]::Create($dest)
    $buf = New-Object byte[] 262144
    $done = 0; $last = -1
    try {
        while (($n = $in.Read($buf, 0, $buf.Length)) -gt 0) {
            $out.Write($buf, 0, $n); $done += $n
            if ($total -gt 0) {
                $pct = [int](100 * $done / $total)
                if ($pct -ge $last + 5) {
                    $last = $pct
                    Emit "DL" "$pct"
                    Say ("    загружено {0}% ({1:N0} из {2:N0} МБ)" -f $pct, ($done / 1MB), ($total / 1MB)) "DarkGray"
                }
            }
        }
    } finally { $out.Close(); $in.Close(); $resp.Close() }
}

function Install-Python($found) {
    # версия, которой у пользователя ещё нет (поверх уже стоящей той же версии установщик python.org
    # только «чинит» её и не добавляет tcl/tk)
    $have = @($found | ForEach-Object { "$($_.Ver.Major).$($_.Ver.Minor)" })
    $choices = @(@{ V = "3.12.10"; Dir = "Python312" }, @{ V = "3.13.9"; Dir = "Python313" })
    $pick = $choices | Where-Object { $have -notcontains $_.V.Substring(0, 4) } | Select-Object -First 1
    if (-not $pick) { $pick = $choices[1] }
    $ver = $pick.V
    $target = Join-Path $env:LOCALAPPDATA ("Programs\Python\" + $pick.Dir + "_ClaudeOverlay")
    $exe = Join-Path $env:TEMP "python-$ver-amd64.exe"
    Emit "PY_DOWNLOAD" $ver
    Say "  Скачиваю Python $ver с python.org (~26 МБ)..." "Cyan"
    try {
        Download "https://www.python.org/ftp/python/$ver/python-$ver-amd64.exe" $exe
    } catch {
        Emit "FAIL" "no_internet"
        throw "Не получилось скачать Python: $($_.Exception.Message). Проверь интернет."
    }
    Emit "PY_INSTALL" $ver
    Say "  Устанавливаю Python $ver только для этой программы (без прав администратора)..." "Cyan"
    $pyArgs = @("/quiet", "InstallAllUsers=0", "PrependPath=0", "Include_launcher=0", "Include_tcltk=1", "Include_pip=1",
              "Include_test=0", "Include_doc=0", "Shortcuts=0", "AssociateFiles=0", "TargetDir=`"$target`"")
    $p = Start-Process -FilePath $exe -ArgumentList $pyArgs -Wait -PassThru
    Remove-Item -LiteralPath $exe -ErrorAction SilentlyContinue
    $r = Test-Python (Join-Path $target "python.exe")
    if (-not $r -or -not $r.Tk) {
        Emit "FAIL" "python_install"
        throw "Python не установился (код $($p.ExitCode)). Поставь вручную с python.org версию 3.12 (галочка «tcl/tk and IDLE»)."
    }
    return $r
}

# ---------------------------------------------------------------- главное

function Main {
    Say ""
    Say "  Claude Overlay — установка компонентов" "White"
    Say "  Папка программы: $AppDir" "DarkGray"
    Say ""
    if (-not (Test-Path -LiteralPath (Join-Path $AppDir "overlay.py"))) {
        Emit "FAIL" "not_unpacked"
        throw "В папке нет overlay.py — сначала распакуй архив целиком («Извлечь всё»)."
    }

    # 1. Python
    Emit "STEP" "python_search"
    Say "[1/3] Ищу Python 3.10-3.14..." "White"
    $py = $null
    if ((Test-Path -LiteralPath $VPy) -and -not $ForceOwnPython) {
        $r = Test-Python $VPy
        if ($r -and $r.Tk) { $py = "venv" }
    }
    if (-not $py) {
        $found = Find-Pythons
        foreach ($f in $found) {
            $note = if ($f.Tk) { "" } else { "  — без компонента tcl/tk (нужен для окон), не подходит" }
            Say ("  нашёл Python {0}: {1}{2}" -f $f.Ver, $f.Exe, $note) "DarkGray"
        }
        $pick = if ($ForceOwnPython) { $null } else { Pick-Python $found }
        if (-not $pick) {
            if ($found.Count -gt 0) { Emit "PY_NO_TK" ""; Say "  Подходящего Python нет — поставлю отдельный, только для программы." "Yellow" }
            $pick = Install-Python $found
        }
        Say ("  Python {0}: {1}" -f $pick.Ver, $pick.Exe) "Green"
        Emit "PY_OK" ("{0}" -f $pick.Ver)
    } else {
        Say "  Окружение программы уже готово." "Green"
        Emit "PY_OK" "venv"
    }

    # 2. окружение .venv
    Emit "STEP" "venv"
    Say "[2/3] Окружение программы (.venv)..." "White"
    if ($py -ne "venv") {
        if (Test-Path -LiteralPath $Venv) {
            $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
            Rename-Item -LiteralPath $Venv -NewName ".venv_old_$stamp"
            Say "  старое окружение сломано — отложил его в .venv_old_$stamp" "Yellow"
        }
        $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        & $pick.Exe -m venv $Venv 2>&1 | ForEach-Object { Say "  $_" "DarkGray" }
        $ErrorActionPreference = $old
        if (-not (Test-Path -LiteralPath $VPy)) { Emit "FAIL" "venv"; throw "Не получилось создать окружение .venv." }
    }
    Say "  готово" "Green"

    # 3. библиотеки
    Emit "STEP" "libs"
    Say "[3/3] Библиотеки (первый раз ~1-2 ГБ, несколько минут)..." "White"
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & $VPy -m pip install --disable-pip-version-check -q --upgrade pip 2>&1 | Out-Null
    $req = Join-Path $AppDir "requirements.txt"
    $n = 0
    & $VPy -m pip install --disable-pip-version-check --progress-bar off -r $req 2>&1 | ForEach-Object {
        $line = "$_"
        if ($line -match '^(Collecting|Downloading|Using cached)\s+(\S+)') {
            $n++
            $name = ($Matches[2] -split '[<>=!~;\[ ]')[0] -replace '\.whl$', ''
            if ($line -like "Collecting*") { Emit "PKG" "$n $name"; Say "  $line" "DarkGray" }
        } elseif ($line -match '^Successfully installed') {
            Say "  $line" "Green"
        } elseif ($line -match 'ERROR|error:') {
            Say "  $line" "Red"
        }
    }
    $pipCode = $LASTEXITCODE
    $ErrorActionPreference = $old
    if ($pipCode -ne 0) {
        Emit "FAIL" "pip"
        throw "Библиотеки не поставились (код $pipCode). Чаще всего — нет интернета или его режет антивирус/прокси. Запусти установку ещё раз: она продолжит."
    }
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & $VPy -c "import faster_whisper, sounddevice, mss, PIL, pynput, matplotlib, pypdf, webview, pystray, numpy" 2>$null
    $ok = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $old
    if (-not $ok) { Emit "FAIL" "imports"; throw "Библиотеки поставились не все — запусти установку ещё раз." }

    # 4. движок окна — Microsoft Edge WebView2 (в Windows 11 уже есть; в Windows 10 бывает не всегда)
    if (-not (Test-WebView2)) {
        Emit "STEP" "webview"
        Say "Ставлю компонент Microsoft Edge WebView2 (нужен окну программы)..." "White"
        $wv = Join-Path $env:TEMP "MicrosoftEdgeWebview2Setup.exe"
        try {
            Invoke-WebRequest -UseBasicParsing -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $wv
            Start-Process -FilePath $wv -ArgumentList "/silent", "/install" -Wait
        } catch {
            Say "  не получилось: $($_.Exception.Message)" "Yellow"
        }
        if (Test-WebView2) { Say "  готово" "Green" }
        else { Say "  Не поставился. Программа подскажет при запуске, где его скачать." "Yellow" }
    }
    Emit "DONE" "0"
    Say ""
    Say "  Готово!" "Green"
}

function Test-WebView2 {
    $id = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    foreach ($k in @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$id",
                     "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$id",
                     "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$id")) {
        $v = (Get-ItemProperty -Path $k -Name pv -ErrorAction SilentlyContinue).pv
        if ($v -and $v -ne "0.0.0.0") { return $true }
    }
    return (Test-Path "${env:ProgramFiles(x86)}\Microsoft\EdgeWebView\Application")
}

if ($ListOnly) {
    Find-Pythons | ForEach-Object { "{0}  tk={1}  {2}" -f $_.Ver, $_.Tk, $_.Exe }
    exit 0
}
try {
    Main
    exit 0
} catch {
    Say ""
    Say ("  ОШИБКА: " + $_.Exception.Message) "Red"
    Emit "DONE" "1"
    if (-not $NoPause) { Read-Host "  Нажми Enter, чтобы закрыть" | Out-Null }
    exit 1
}
