; Script Inno Setup pour InstantPrint.
; Compile avec Inno Setup 6 :  iscc installer\instantprint.iss
; Produit  installer\Output\InstantPrint-Setup.exe
;
; Prérequis : avoir déjà lancé  pyinstaller instantprint.spec  (crée dist\InstantPrint\).

#define MyAppName "InstantPrint"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "InstantPrint"
#define MyAppExeName "InstantPrint.exe"

[Setup]
AppId={{B7E4B0F2-4A2E-4C9A-9D3F-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Installe dans Program Files -> droits admin. Mets "lowest" pour installer
; par-utilisateur sans admin (DefaultDirName={localappdata}\... dans ce cas).
PrivilegesRequired=admin
OutputDir=Output
OutputBaseFilename=InstantPrint-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=app.ico

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Tout le dossier produit par PyInstaller.
Source: "..\dist\InstantPrint\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
