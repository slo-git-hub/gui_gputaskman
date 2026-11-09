; Inno Setup 6 script for the GPU Task Manager desktop app (gtm-gui.exe) plus the console gputaskman.exe.
; Built by tools/build_installer.py from the extracted portable ZIP; it passes the defines below.
; Per-user install by default (no admin): %LOCALAPPDATA%\Programs\GPU Task Manager.

#ifndef AppVersion
  #error AppVersion must be defined (tools/build_installer.py passes it)
#endif
#ifndef SourceDir
  #error SourceDir must be defined: the extracted portable folder
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif
#ifndef Arch
  #define Arch "x64"
#endif
#ifndef Root
  #define Root ".."
#endif

#define AppName "GPU Task Manager"
#define RunKey "Software\Microsoft\Windows\CurrentVersion\Run"

[Setup]
AppId={{109F3436-5A46-4BDC-BECE-7CBCADAF3F19}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=gputaskman contributors
AppPublisherURL=https://github.com/slo-git-hub/gui_gputaskman
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
#if Arch == "arm64"
ArchitecturesAllowed=arm64
ArchitecturesInstallIn64BitMode=arm64
#else
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#endif
OutputDir={#OutputDir}
OutputBaseFilename=GPUTaskManager-{#AppVersion}-Setup-{#Arch}
SetupIconFile={#Root}\tools\gtm-gui.ico
UninstallDisplayIcon={app}\gtm-gui.exe
UninstallDisplayName={#AppName}
LicenseFile={#SourceDir}\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Close a running gtm-gui.exe (tray) before files are replaced or removed.
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "autostart"; Description: "Start with Windows (opens in the tray)"; GroupDescription: "Startup:"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\gtm-gui.exe"
Name: "{group}\{#AppName} (terminal)"; Filename: "{app}\gputaskman.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\gtm-gui.exe"; Tasks: desktopicon

[Registry]
; Same value the tray menu's "Start with Windows" toggle writes (src/gputaskman/autostart.py).
Root: HKCU; Subkey: "{#RunKey}"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\gtm-gui.exe"" --tray"; Tasks: autostart
; Always removed on uninstall, including when it was turned on later from the tray menu.
Root: HKCU; Subkey: "{#RunKey}"; ValueType: none; ValueName: "{#AppName}"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\gtm-gui.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM gtm-gui.exe /F"; Flags: runhidden; RunOnceId: "StopGui"
