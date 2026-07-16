; Race Engineer per-user installer (B2 spec 3.1-3.2).
; Compile:  ISCC.exe installer\race-engineer.iss /DAppVersion=<version>
; Prereqs:  scripts/build_release.py has run (fresh core/config/_baked.py),
;           and uv.exe sits at installer\uv.exe (see docs/RELEASING.md).
; Layout: {localappdata}\RaceEngineer IS the code root (flat) - app/,
; core/, scripts/, pyproject.toml, uv.lock, .python-version, uv.exe,
; plus the preserved data/, .env and .venv the app creates.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{B2E31A6F-8A44-4C58-9A02-6E1F4CE3D761}}
AppName=Race Engineer
AppVersion={#AppVersion}
AppPublisher=Race Engineer
DefaultDirName={localappdata}\RaceEngineer
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=RaceEngineer-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs ignoreversion; Excludes: "__pycache__\*,*.pyc"
Source: "..\core\*"; DestDir: "{app}\core"; Flags: recursesubdirs ignoreversion; Excludes: "__pycache__\*,*.pyc"
Source: "..\scripts\*"; DestDir: "{app}\scripts"; Flags: recursesubdirs ignoreversion; Excludes: "__pycache__\*,*.pyc"
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\uv.lock"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\.python-version"; DestDir: "{app}"; Flags: ignoreversion
Source: "uv.exe"; DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "{app}\uv.exe"; Parameters: "sync"; WorkingDir: "{app}"; StatusMsg: "Installing Python and dependencies (a few minutes on first install)..."; Flags: runhidden
Filename: "{app}\.venv\Scripts\python.exe"; Parameters: """{app}\scripts\install_shortcut.py"" --target tray"; WorkingDir: "{app}"; StatusMsg: "Creating the desktop shortcut..."; Flags: runhidden
Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\scripts\tray_app.py"""; WorkingDir: "{app}"; Description: "Start Race Engineer now"; Flags: postinstall nowait
Filename: "http://localhost:8501/"; Description: "Open Race Engineer in the browser (first run lands on Setup)"; Flags: postinstall shellexec nowait skipifsilent

[UninstallRun]
Filename: "{app}\.venv\Scripts\python.exe"; Parameters: """{app}\scripts\stop_all.py"""; WorkingDir: "{app}"; Flags: runhidden; RunOnceId: "StopRig"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { The venv is a machine artifact - always removed. }
    DelTree(ExpandConstant('{app}\.venv'), True, True, True);
    { Race history and keys survive unless the user opts out (spec 3.2). }
    if DirExists(ExpandConstant('{app}\data')) or
       FileExists(ExpandConstant('{app}\.env')) then
    begin
      if MsgBox('Also delete your race history and saved keys ' +
                '(data folder and .env)?',
                mbConfirmation, MB_YESNO) = IDYES then
      begin
        DelTree(ExpandConstant('{app}\data'), True, True, True);
        DeleteFile(ExpandConstant('{app}\.env'));
        RemoveDir(ExpandConstant('{app}'));
      end;
    end;
  end;
end;
