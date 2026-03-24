; NiftyTrader Intelligence — Inno Setup Script
; Creates a professional Windows installer .exe
;
; Requirements: Inno Setup 6  (https://jrsoftware.org/isdl.php)
; Compile with: iscc installer.iss
; Output:       dist\NiftyTrader_v2_Installer.exe
;
; The resulting .exe is a self-contained single-file installer with:
;  - Welcome / license / progress wizard pages
;  - Embedded Python 3.10 + all packages
;  - Desktop shortcut + Start Menu entry
;  - Uninstaller registered in Windows Add/Remove Programs
;  - NO command prompt shown at any point

#define AppName    "NiftyTrader Intelligence"
#define AppVersion "2.0"
#define AppPublisher "NiftyTrader"
#define AppURL     "https://github.com/yourrepo/niftytrader"
#define AppExeName "NiftyTrader.vbs"
#define InstallDir "{autopf}\NiftyTrader"

[Setup]
AppId={{8F3A9B2C-4E1D-4F7A-B8C3-2A9E5D6F1234}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
DefaultDirName={autopf}\NiftyTrader
DefaultGroupName=NiftyTrader
OutputDir=dist
OutputBaseFilename=NiftyTrader_v2_Installer
SetupIconFile=installer\resources\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DisableProgramGroupPage=no
; Show no command prompt during installation
CreateUninstallRegKey=yes
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\NiftyTrader.vbs

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Additional icons:"; Flags: checked

[Files]
; Python 3.10 embeddable runtime — entire folder
Source: "dist\NiftyTrader_Setup\python_embed\*"; DestDir: "{app}\python"; Flags: recursesubdirs createallsubdirs

; Python packages (wheels) — already downloaded
Source: "dist\NiftyTrader_Setup\packages\*"; DestDir: "{app}\packages"; Flags: recursesubdirs createallsubdirs

; get-pip.py bootstrap
Source: "dist\NiftyTrader_Setup\resources\get-pip.py"; DestDir: "{app}\resources"

; NiftyTrader application source
Source: "dist\NiftyTrader_Setup\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs createallsubdirs

; Launcher VBScript
Source: "installer\NiftyTrader.vbs"; DestDir: "{app}"

; Uninstaller helper
Source: "installer\resources\icon.ico"; DestDir: "{app}"; Flags: dontcopy

[Dirs]
Name: "{app}\logs"
Name: "{app}\auth"
Name: "{app}\models"

[Icons]
; Desktop shortcut — wscript with style 0 hides console
Name: "{autodesktop}\NiftyTrader"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\NiftyTrader.vbs"""; WorkingDir: "{app}\app"; IconFilename: "{app}\resources\icon.ico"; Tasks: desktopicon
; Start menu
Name: "{group}\NiftyTrader"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\NiftyTrader.vbs"""; WorkingDir: "{app}\app"; IconFilename: "{app}\resources\icon.ico"
Name: "{group}\Uninstall NiftyTrader"; Filename: "{uninstallexe}"

[Run]
; After files are copied, install pip into embedded Python
Filename: "{app}\python\python.exe"; Parameters: "{app}\resources\get-pip.py --no-warn-script-location --quiet"; Flags: runhidden waituntilterminated; StatusMsg: "Setting up pip..."

; Fix embedded Python's .pth file to enable site-packages
Filename: "{app}\python\python.exe"; Parameters: "-c ""import sys; open(r'{app}\python\python310._pth', 'a').write('\nimport site\nLib\nLib\\site-packages\n')"""; Flags: runhidden waituntilterminated; StatusMsg: "Configuring Python..."

; Install all packages from bundled wheels
Filename: "{app}\python\python.exe"; Parameters: "-m pip install --no-index --find-links ""{app}\packages"" PySide6 pandas numpy SQLAlchemy requests --quiet --no-warn-script-location"; Flags: runhidden waituntilterminated; StatusMsg: "Installing packages (this takes ~2 minutes)..."

; Launch after install
Filename: "{sys}\wscript.exe"; Parameters: """{app}\NiftyTrader.vbs"""; Flags: nowait postinstall skipifsilent; Description: "Launch NiftyTrader now"

[UninstallRun]
; Kill any running NiftyTrader process
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM python.exe /FI ""WINDOWTITLE eq NiftyTrader*"""; Flags: runhidden; RunOnceId: "KillApp"

[Code]
// Custom Inno Setup Pascal script — progress messages during package install

var
  ProgressPage: TOutputProgressWizardPage;

procedure InitializeWizard;
begin
  ProgressPage := CreateOutputProgressPage(
    'Installing packages',
    'Please wait while Python packages are installed...'
  );
end;
