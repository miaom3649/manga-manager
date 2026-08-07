#define MyAppName "H库"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "HLibrary"
#define MyAppExeName "HLibrary.exe"

[Setup]
AppId={{85CB06A6-848C-48C3-A3C5-37DF0ED06BE6}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\HLibrary
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\build-output\installer
OutputBaseFilename=HLibrary-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName}

[Languages]
; 简体中文属于 Inno Setup 的贡献翻译，不随 Chocolatey 安装包附带。
; 构建脚本会从 Inno Setup 官方源码仓库下载到本文件旁边。
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标："; Flags: unchecked

[Files]
Source: "..\dist\HLibrary\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName}（调试）"; Filename: "{app}\HLibrary-Debug.exe"; Comment: "显示诊断日志窗口，仅用于测试"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    MsgBox('手机访问需要 Windows 允许 H库 通过私人网络通信。首次出现防火墙提示时，请只勾选“专用网络”。', mbInformation, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    if MsgBox('是否同时删除 H库 的数据库、设置和缩略图缓存？漫画 ZIP、插画原图和主目录内备份不会被删除。', mbConfirmation, MB_YESNO) = IDYES then
      DelTree(ExpandConstant('{localappdata}\HLibrary'), True, True, True);
  end;
end;
