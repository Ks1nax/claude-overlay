; EXE-установщик Claude Overlay (Inno Setup 6). Сборка: setup\build.bat → Zip\ClaudeOverlay-Setup-<версия>.exe
; Ставит программу в выбранную папку (по умолчанию — для текущего пользователя, без прав администратора), потом
; на странице с прогрессом запускает setup\install.ps1: Python (найти или поставить), окружение .venv, библиотеки.
; Удаление — через «Параметры → Приложения» (спросит про материалы и модели).

#define AppName "Claude Overlay"
#ifndef AppVersion
  #define AppVersion "2.4.0"
#endif

[Setup]
AppId={{8F2C5A41-6B1E-4D7A-9C3E-2B7F0D4A9E11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Ks1nax
AppPublisherURL=https://github.com/Ks1nax/claude-overlay
AppSupportURL=https://github.com/Ks1nax/claude-overlay/issues
DefaultDirName={localappdata}\Programs\Claude Overlay
DisableProgramGroupPage=yes
DisableDirPage=no
DisableWelcomePage=no
PrivilegesRequired=lowest
OutputDir=..\Zip
OutputBaseFilename=ClaudeOverlay-Setup-{#AppVersion}
SetupIconFile=..\app\icon.ico
UninstallDisplayIcon={app}\app\icon.ico
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=wizard_large.png
WizardSmallImageFile=wizard_small.png
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=no
SetupLogging=yes

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Messages]
ru.WelcomeLabel2=Будет установлен [name/ver] — голосовой помощник поверх всех окон:%n%n• «Клод, …» голосом или текстом — ответ по экрану;%n• F7 — вопрос со звука компьютера (лекция, созвон);%n• окно не видно на демонстрации экрана.%n%nПонадобится интернет: установщик сам найдёт или поставит Python и скачает библиотеки распознавания речи (первый раз — несколько минут).
ru.FinishedLabel=Готово! [name] установлен.%n%nЗапускай его значком «Claude Overlay» на рабочем столе или в меню «Пуск».

[Tasks]
Name: "desktopicon"; Description: "Значок на рабочем столе"; GroupDescription: "Значки:"
Name: "autostart"; Description: "Запускать вместе с Windows"; GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
Source: "..\overlay.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\app\*.py"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\icon.ico"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "..\app\icon.png"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "install.ps1"; DestDir: "{app}\setup"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\КАК ЗАПУСТИТЬ.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Промпт для конспекта.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Установить.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\start.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{userprograms}\Claude Overlay"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\overlay.py"""; WorkingDir: "{app}"; IconFilename: "{app}\app\icon.ico"; Comment: "Голосовой помощник Claude поверх всех окон"
Name: "{userdesktop}\Claude Overlay"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\overlay.py"""; WorkingDir: "{app}"; IconFilename: "{app}\app\icon.ico"; Comment: "Голосовой помощник Claude поверх всех окон"; Tasks: desktopicon
Name: "{userstartup}\Claude Overlay"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\overlay.py"""; WorkingDir: "{app}"; IconFilename: "{app}\app\icon.ico"; Tasks: autostart

[Run]
Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\overlay.py"" --wizard"; WorkingDir: "{app}"; Description: "Открыть мастер настройки (вход в Claude, модели, микрофон)"; Flags: postinstall nowait skipifsilent; Check: DepsOk

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\.venv_old_*"
Type: filesandordirs; Name: "{app}\app\__pycache__"

[Code]
var
  DepsPage: TOutputProgressWizardPage;
  DepsResult: Boolean;
  FailKey: String;

function DepsOk: Boolean;
begin
  Result := DepsResult;
end;

procedure StopOverlay;
var
  Code: Integer;
  Dir: String;
begin
  { работающий оверлей держит файлы — закрываем его (только копию из этой папки) }
  Dir := ExpandConstant('{app}');
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine -like ''*' + Dir + '*overlay.py*'' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"',
    '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopOverlay;
  Result := '';
end;

procedure OnLog(const S: String; const Error, FirstLine: Boolean);
var
  L, Key, Arg, Name: String;
  P, N: Integer;
begin
  L := Trim(S);
  if Copy(L, 1, 2) <> '@@' then Exit;
  L := Copy(L, 3, Length(L));
  P := Pos(' ', L);
  if P > 0 then begin
    Key := Copy(L, 1, P - 1);
    Arg := Trim(Copy(L, P + 1, Length(L)));
  end else begin
    Key := L;
    Arg := '';
  end;
  if Key = 'STEP' then begin
    if Arg = 'python_search' then begin
      DepsPage.SetText('Ищу Python на компьютере…', '');
      DepsPage.SetProgress(3, 100);
    end else if Arg = 'venv' then begin
      DepsPage.SetText('Создаю окружение программы…', '');
      DepsPage.SetProgress(30, 100);
    end else if Arg = 'libs' then begin
      DepsPage.SetText('Скачиваю и ставлю библиотеки распознавания речи (первый раз — несколько минут)…', '');
      DepsPage.SetProgress(34, 100);
    end;
  end else if Key = 'PY_NO_TK' then
    DepsPage.SetText('Подходящего Python нет — поставлю отдельный, только для программы…', '')
  else if Key = 'PY_DOWNLOAD' then
    DepsPage.SetText('Скачиваю Python ' + Arg + ' с python.org (~26 МБ)…', '')
  else if Key = 'DL' then begin
    N := StrToIntDef(Arg, 0);
    DepsPage.SetText('Скачиваю Python с python.org…', 'загружено ' + Arg + '%');
    DepsPage.SetProgress(4 + N * 16 div 100, 100);
  end else if Key = 'PY_INSTALL' then begin
    DepsPage.SetText('Устанавливаю Python ' + Arg + ' (только для этой программы, без прав администратора)…', '');
    DepsPage.SetProgress(22, 100);
  end else if Key = 'PY_OK' then begin
    if Arg = 'venv' then
      DepsPage.SetText('Окружение программы уже есть — проверяю библиотеки…', '')
    else
      DepsPage.SetText('Нашёл Python ' + Arg, '');
    DepsPage.SetProgress(28, 100);
  end else if Key = 'PKG' then begin
    P := Pos(' ', Arg);
    N := StrToIntDef(Copy(Arg, 1, P - 1), 0);
    Name := Copy(Arg, P + 1, Length(Arg));
    DepsPage.SetText('Скачиваю и ставлю библиотеки распознавания речи…', Name);
    N := 34 + N * 60 div 55;
    if N > 95 then N := 95;
    DepsPage.SetProgress(N, 100);
  end else if Key = 'FAIL' then
    FailKey := Arg
  else if (Key = 'DONE') and (Arg = '0') then
    DepsPage.SetProgress(100, 100);
end;

function FailText: String;
begin
  if FailKey = 'no_internet' then
    Result := 'Не получилось скачать Python. Проверь интернет (и VPN/прокси, если есть).'
  else if FailKey = 'pip' then
    Result := 'Библиотеки не скачались. Чаще всего — нет интернета или его режет антивирус/прокси.'
  else if FailKey = 'python_install' then
    Result := 'Python не установился. Можно поставить его вручную с python.org (версия 3.12, галочка «tcl/tk and IDLE»), потом нажать «Повторить».'
  else if FailKey = 'venv' then
    Result := 'Не получилось создать окружение программы.'
  else if FailKey = 'imports' then
    Result := 'Библиотеки поставились не все.'
  else
    Result := 'Установка компонентов не удалась.';
  Result := Result + #13#10#13#10 + '«Повторить» — попробовать ещё раз (продолжит с того же места).' + #13#10 +
            '«Отмена» — закончить сейчас; позже можно запустить «Установить.bat» в папке программы.';
end;

function RunDeps: Boolean;
var
  Code: Integer;
  Params: String;
begin
  FailKey := '';
  Params := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\setup\install.ps1') +
            '" -AppDir "' + ExpandConstant('{app}') + '" -NoPause';
  DepsPage.SetText('Готовлюсь…', '');
  DepsPage.SetProgress(0, 100);
  DepsPage.Show;
  try
    Result := ExecAndLogOutput(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Params,
                               ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, Code, @OnLog)
              and (Code = 0);
  finally
    DepsPage.Hide;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    DepsPage := CreateOutputProgressPage('Устанавливаю компоненты',
      'Python, распознавание речи и всё, что нужно программе. Нужен интернет.');
    repeat
      DepsResult := RunDeps;
      if DepsResult then Break;
      if SuppressibleMsgBox(FailText, mbError, MB_RETRYCANCEL, IDCANCEL) <> IDRETRY then Break;
    until False;
  end;
end;

procedure DeleteModels;
var
  Hub: String;
  I: Integer;
  Names: array of String;
begin
  Hub := GetEnv('HF_HUB_CACHE');
  if Hub = '' then
    if GetEnv('HF_HOME') <> '' then Hub := AddBackslash(GetEnv('HF_HOME')) + 'hub'
    else Hub := ExpandConstant('{%USERPROFILE}\.cache\huggingface\hub');
  SetArrayLength(Names, 7);
  Names[0] := 'models--Systran--faster-whisper-tiny';
  Names[1] := 'models--Systran--faster-whisper-base';
  Names[2] := 'models--Systran--faster-whisper-small';
  Names[3] := 'models--Systran--faster-whisper-medium';
  Names[4] := 'models--Systran--faster-whisper-large-v3';
  Names[5] := 'models--mobiuslabsgmbh--faster-whisper-large-v3-turbo';
  Names[6] := 'models--Systran--faster-distil-whisper-large-v3';
  for I := 0 to GetArrayLength(Names) - 1 do
    DelTree(AddBackslash(Hub) + Names[I], True, True, True);
end;

procedure DeleteLongTree(const Dir: String);
var
  Code: Integer;
begin
  { rmdir с префиксом \\?\ удаляет и пути длиннее 260 символов (глубокие папки библиотек в .venv) }
  if DirExists(Dir) then
    Exec(ExpandConstant('{cmd}'), '/c rmdir /s /q "\\?\' + Dir + '"', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then begin
    StopOverlay;
    DeleteLongTree(ExpandConstant('{app}\.venv'));
  end;
  if CurUninstallStep = usPostUninstall then begin
    if DirExists(ExpandConstant('{app}\workspace')) then
      if SuppressibleMsgBox('Удалить и твои материалы, настройки и историю вопросов (папка workspace)?' + #13#10 +
                            'Если собираешься поставить программу снова — нажми «Нет», всё сохранится.',
                            mbConfirmation, MB_YESNO, IDNO) = IDYES then
        DelTree(ExpandConstant('{app}\workspace'), True, True, True);
    if SuppressibleMsgBox('Удалить скачанные модели распознавания речи (до 6 ГБ)?', mbConfirmation, MB_YESNO,
                          IDNO) = IDYES then
      DeleteModels;
    RemoveDir(ExpandConstant('{app}\setup'));
    RemoveDir(ExpandConstant('{app}'));
  end;
end;
