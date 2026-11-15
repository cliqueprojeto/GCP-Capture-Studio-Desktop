; Instalador do GCP Capture Studio para Windows (Inno Setup 6)
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "GCP Capture Studio"
#define AppExe "GCP Capture Studio.exe"

[Setup]
AppId={{6B1E2B7C-6E0B-4F6E-9C55-2F1C7A1D9A31}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Bruno Albertini | Gestão Cultural Pro
AppPublisherURL=https://gestaoculturalpro.com.br
AppSupportURL=https://github.com/cliqueprojeto/GCP-Capture-Studio-Desktop
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=GCP-Capture-Studio-{#AppVersion}-Windows-x64
SetupIconFile=app.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
CloseApplications=yes
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\GCP Capture Studio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
