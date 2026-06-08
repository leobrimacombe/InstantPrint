; Script Inno Setup pour Mesh Repair.
; Compile avec Inno Setup 6 :  iscc installer\mesh-repair.iss
; Produit  installer\Output\MeshRepair-Setup.exe
;
; Prérequis : avoir déjà lancé  pyinstaller mesh-repair.spec  (crée dist\MeshRepair\).

#define MyAppName "Mesh Repair"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Mesh Repair"
#define MyAppExeName "MeshRepair.exe"

[Setup]
AppId={{B7E4B0F2-4A2E-4C9A-9D3F-MESHREPAIR0001}
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
OutputBaseFilename=MeshRepair-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Décommente quand tu as une icône :
; SetupIconFile=app.ico

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Tout le dossier produit par PyInstaller.
Source: "..\dist\MeshRepair\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Désinstaller {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
