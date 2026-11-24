; withoutvisit installer.
;
; Auto-update contract, matched by app/updater.py:
;   the running app downloads this file (asset name withoutvisit_Setup.exe) and runs
;   withoutvisit_Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /AUTOUPDATE
;   then exits. This script waits until mutex "withoutvisit" is gone, replaces
;   {app}, and starts withoutvisit.exe again.
;
; Install is per-user (%LOCALAPPDATA%\withoutvisit\app) so a background update
; does not need administrator rights. Settings stay in the parent folder
; (%LOCALAPPDATA%\withoutvisit) and are not part of {app}.
; device.json is not shipped; an upgrade overwrites action.py and leaves it.
;
; AppVersion must stay in sync with APP_VERSION in app/config.py.

#define AppName "withoutvisit"
#define AppVersion "0.1.0"
#define AppExe "withoutvisit.exe"
#define AppMutex "withoutvisit"
#define AppId "{{8F4C2A19-6B7E-4D35-9A10-C3E5F7B28D64}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=withoutvisit
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\withoutvisit\app
DisableProgramGroupPage=yes
DisableDirPage=auto
DisableReadyPage=yes
UsePreviousAppDir=yes
OutputDir=..\dist
OutputBaseFilename=withoutvisit_Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no
MinVersion=10.0

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: checkedonce

[Files]
Source: "..\dist\withoutvisit\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "device.json"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Flags: nowait; Check: IsAutoUpdate

[Code]
function IsAutoUpdate: Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/AUTOUPDATE') = 0 then
    begin
      Result := True;
      Exit;
    end;
end;

function InitializeSetup: Boolean;
var
  I: Integer;
begin
  Result := True;
  if not IsAutoUpdate then
    Exit;
  { The app starts us, then exits and releases the mutex. Wait so we do not
    replace withoutvisit.exe while that process still has it open. }
  for I := 1 to 60 do
  begin
    if not CheckForMutexes('{#AppMutex}') then
      Exit;
    Sleep(500);
  end;
end;
