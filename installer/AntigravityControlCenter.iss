; Antigravity Control Center — Per-User Windows Installer (Inno Setup 6)
; WARNING: Never change AppId; it uniquely identifies upgrades in Windows Uninstall registry.

#ifndef AppVersion
  #define AppVersion "1.4.0"
#endif

[Setup]
AppId={{6E3A9B14-7C2D-4F8A-9B51-2D8E4C7A1F03}}
AppName=Antigravity Control Center
AppVersion={#AppVersion}
AppVerName=Antigravity Control Center {#AppVersion}
AppPublisher=Antigravity Control Center
AppPublisherURL=https://github.com/3bdyna/Antigravity-Control-Center
AppSupportURL=https://github.com/3bdyna/Antigravity-Control-Center/issues
AppUpdatesURL=https://github.com/3bdyna/Antigravity-Control-Center/releases
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\AntigravityControlCenter
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\release
OutputBaseFilename=AntigravityControlCenter-Setup-{#AppVersion}
SetupIconFile=..\app_icon.ico
UninstallDisplayIcon={app}\AntigravityControlCenter.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex=Local\AntigravityControlCenterDaemon,Local\AntigravityControlCenterUI
CloseApplications=force
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Clean stale PyInstaller runtime binaries on upgrade. User data lives outside {app} and is never touched.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; Core PyInstaller application bundle
Source: "..\dist\AntigravityControlCenter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Companion runtime scripts expected in {app} by AntigravityAsarWatchdog and drag daemon
Source: "..\scripts\auto_patch_antigravity.js"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\antigravity-drag-daemon.js"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\antigravity_drag_daemon.pyw"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\run_daemon.vbs"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\start-drag-daemon.vbs"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Antigravity Control Center"; Filename: "{app}\AntigravityControlCenter.exe"
Name: "{autodesktop}\Antigravity Control Center"; Filename: "{app}\AntigravityControlCenter.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AntigravityControlCenter.exe"; Description: "{cm:LaunchProgram,Antigravity Control Center}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\AntigravityControlCenter.exe"; Flags: nowait skipifnotsilent; Check: ShouldRelaunchAfterSilentUpdate

[Code]
function HasCommandLineSwitch(const SwitchName: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
  begin
    if CompareText(ParamStr(I), SwitchName) = 0 then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function ShouldRelaunchAfterSilentUpdate(): Boolean;
begin
  Result := HasCommandLineSwitch('/RELAUNCH');
end;

function InitializeSetup(): Boolean;
var
  WaitedMs: Integer;
begin
  WaitedMs := 0;
  // Wait up to 12 seconds for exiting daemon and UI mutexes to clear during silent upgrades
  while (WaitedMs < 12000) and
        (CheckForMutexes('Local\AntigravityControlCenterDaemon') or
         CheckForMutexes('Local\AntigravityControlCenterUI')) do
  begin
    Sleep(250);
    WaitedMs := WaitedMs + 250;
  end;
  Result := True;
end;
