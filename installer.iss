[Setup]
AppId={{B7D5B4F6-6F65-4F4B-9B2A-BITRIXPOLICYHUB}
AppName=Bitrix Policy Automation Hub
AppVersion=1.0.0
AppPublisher=SINEDIS
DefaultDirName={autopf}\Bitrix Policy Automation Hub
DefaultGroupName=Bitrix Policy Automation Hub
OutputDir=installer_output
OutputBaseFilename=BitrixPolicyAutomationHubSetup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\BitrixPolicyAutomationHub.exe

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные параметры:"

[Files]
Source: "dist\BitrixPolicyAutomationHub\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Bitrix Policy Automation Hub"; Filename: "{app}\BitrixPolicyAutomationHub.exe"; WorkingDir: "{app}"
Name: "{commondesktop}\Bitrix Policy Automation Hub"; Filename: "{app}\BitrixPolicyAutomationHub.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\BitrixPolicyAutomationHub.exe"; Description: "Запустить Bitrix Policy Automation Hub"; Flags: nowait postinstall skipifsilent