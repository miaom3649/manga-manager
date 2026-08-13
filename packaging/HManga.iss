#define MyAppName "HManガ"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "hmanga"
#define MyAppExeName "HManga.exe"

[Setup]
AppId={{85CB06A6-848C-48C3-A3C5-37DF0ED06BE6}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\hmanga
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\build-output\installer
OutputBaseFilename=HManga-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName}

[Languages]
; Simplified Chinese is a contributed Inno Setup translation and is not bundled
; with the Chocolatey package. The build downloads it from the official repository.
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "..\dist\HManga\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName} (Debug)"; Filename: "{app}\HManga-Debug.exe"; Comment: "Show diagnostic logs for testing"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    MsgBox('Mobile access requires Windows to allow HManガ on private networks. Select only Private networks when the firewall prompt appears.', mbInformation, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if MsgBox('Also remove the HManガ database, settings, and thumbnail cache? Comic ZIP files, original illustrations, and backups in the library directory will not be removed.', mbConfirmation, MB_YESNO) = IDYES then
      DelTree(ExpandConstant('{localappdata}\hmanga'), True, True, True);
  end;
end;
