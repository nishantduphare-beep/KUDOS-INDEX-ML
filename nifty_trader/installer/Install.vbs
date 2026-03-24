' ════════════════════════════════════════════════════════════════
' NiftyTrader Intelligence  v2.0  —  Installer
' ════════════════════════════════════════════════════════════════
' Double-click this file.  No admin rights needed.
' Installs to your personal AppData folder — no permission issues.
' ════════════════════════════════════════════════════════════════
Option Explicit

On Error Resume Next

Dim oShell, oFSO, oWS
Set oShell = CreateObject("WScript.Shell")
Set oFSO   = CreateObject("Scripting.FileSystemObject")
Set oWS    = CreateObject("WScript.Shell")

' ── Install to AppData\Local — never needs admin or permission ────
Dim appData    : appData    = oShell.ExpandEnvironmentStrings("%LOCALAPPDATA%")
Dim srcDir     : srcDir     = oFSO.GetParentFolderName(WScript.ScriptFullName)
Dim installDir : installDir = appData & "\NiftyTrader"
Dim pyDir      : pyDir      = installDir & "\python"
Dim pkgDir     : pkgDir     = installDir & "\packages"
Dim appDir     : appDir     = installDir & "\app"
Dim resDir     : resDir     = installDir & "\resources"

' ── Welcome dialog ───────────────────────────────────────────────
Dim welcome
welcome = MsgBox( _
    "NiftyTrader Intelligence  v2.0" & vbCrLf & vbCrLf & _
    "Install location:" & vbCrLf & _
    installDir & vbCrLf & vbCrLf & _
    "  Python 3.10 runtime    (bundled)" & vbCrLf & _
    "  All packages            (bundled)" & vbCrLf & _
    "  Desktop shortcut       (created)" & vbCrLf & _
    "  Start Menu entry       (created)" & vbCrLf & vbCrLf & _
    "Estimated time:  2-3 minutes" & vbCrLf & vbCrLf & _
    "Click OK to install.", _
    vbOKCancel + vbInformation, "NiftyTrader Installer")

If welcome = vbCancel Then
    WScript.Quit
End If

' ── Validate source folder ───────────────────────────────────────
If Not oFSO.FolderExists(srcDir & "\python_embed") Then
    MsgBox "Setup files are missing." & vbCrLf & vbCrLf & _
           "Make sure you extracted the full" & vbCrLf & _
           "NiftyTrader_Setup folder before running Install.vbs.", _
           vbCritical, "NiftyTrader Installer"
    WScript.Quit
End If

' ── Step 1: Create directories ───────────────────────────────────
ShowStep "Creating folders..."
SafeMkDir installDir
SafeMkDir pyDir
SafeMkDir pkgDir
SafeMkDir appDir
SafeMkDir resDir
SafeMkDir installDir & "\logs"
SafeMkDir installDir & "\auth"
SafeMkDir installDir & "\models"

If Err.Number <> 0 Then
    MsgBox "Could not create install folder:" & vbCrLf & installDir & vbCrLf & vbCrLf & _
           "Error: " & Err.Description, vbCritical, "NiftyTrader Installer"
    WScript.Quit
End If

' ── Step 2: Copy Python runtime ──────────────────────────────────
ShowStep "Copying Python 3.10 runtime..."
CopyFolder srcDir & "\python_embed", pyDir
If Err.Number <> 0 Then
    MsgBox "Failed to copy Python runtime." & vbCrLf & "Error: " & Err.Description, _
           vbCritical, "NiftyTrader Installer"
    WScript.Quit
End If

' ── Step 3: Copy packages ────────────────────────────────────────
ShowStep "Copying packages..."
CopyFolder srcDir & "\packages", pkgDir

' ── Step 4: Copy app and resources ──────────────────────────────
ShowStep "Copying application files..."
CopyFolder srcDir & "\resources", resDir
CopyFolder srcDir & "\app",       appDir

' ── Step 5: Fix Python embed + install packages ──────────────────
ShowStep "Setting up Python (please wait 1-2 minutes)..."
FixPthFile pyDir

' Install pip silently
Dim getPip : getPip = resDir & "\get-pip.py"
If oFSO.FileExists(getPip) Then
    RunHidden pyDir & "\python.exe """ & getPip & """ --no-warn-script-location --quiet"
End If

' Install packages from bundled wheels — no internet needed
ShowStep "Installing packages..."
InstallPackages pyDir, pkgDir

' ── Step 6: Write launcher + shortcuts ───────────────────────────
ShowStep "Creating shortcuts..."
WriteLauncher installDir, pyDir, appDir
WriteUninstaller installDir, pyDir

' Desktop shortcut
Dim desktop : desktop = oWS.SpecialFolders("Desktop")
MakeShortcut desktop & "\NiftyTrader.lnk", _
             "wscript.exe", """" & installDir & "\NiftyTrader.vbs""", appDir

' Start Menu
Dim smDir : smDir = oWS.SpecialFolders("StartMenu") & "\Programs\NiftyTrader"
SafeMkDir smDir
MakeShortcut smDir & "\NiftyTrader.lnk", _
             "wscript.exe", """" & installDir & "\NiftyTrader.vbs""", appDir
MakeShortcut smDir & "\Uninstall.lnk", _
             "wscript.exe", """" & installDir & "\Uninstall.vbs""", installDir

' ── Done ─────────────────────────────────────────────────────────
MsgBox "NiftyTrader has been installed!" & vbCrLf & vbCrLf & _
       "A shortcut has been placed on your Desktop." & vbCrLf & _
       "Start Menu  ->  NiftyTrader  ->  NiftyTrader" & vbCrLf & vbCrLf & _
       "Click OK to launch the app now.", _
       vbInformation, "Installation Complete"

' Launch app (no console window)
oShell.Run "wscript.exe """ & installDir & "\NiftyTrader.vbs""", 0, False
WScript.Quit


' ════════════════════════════════════════════════════════════════
'  HELPERS
' ════════════════════════════════════════════════════════════════

Sub ShowStep(msg)
    ' Update title of a background cmd window — lightweight progress feedback
    On Error Resume Next
    oShell.Run "cmd /c title NiftyTrader Installer: " & msg, 0, False
    On Error GoTo 0
End Sub

Sub SafeMkDir(path)
    On Error Resume Next
    If Not oFSO.FolderExists(path) Then oFSO.CreateFolder path
    On Error GoTo 0
End Sub

Sub RunHidden(cmd)
    On Error Resume Next
    oShell.Run "cmd /c """ & cmd & """ >NUL 2>&1", 0, True
    On Error GoTo 0
End Sub

Sub CopyFolder(src, dst)
    If Not oFSO.FolderExists(src) Then Exit Sub
    On Error Resume Next
    Dim f, sf
    For Each f In oFSO.GetFolder(src).Files
        oFSO.CopyFile f.Path, dst & "\" & f.Name, True
    Next
    For Each sf In oFSO.GetFolder(src).SubFolders
        SafeMkDir dst & "\" & sf.Name
        CopyFolder sf.Path, dst & "\" & sf.Name
    Next
    On Error GoTo 0
End Sub

Sub FixPthFile(pyDir)
    On Error Resume Next
    Dim names(3), i, pthPath, ts, content, tw
    names(0) = "python310._pth"
    names(1) = "python3._pth"
    names(2) = "python._pth"
    names(3) = "python310.pth"
    For i = 0 To 3
        pthPath = pyDir & "\" & names(i)
        If oFSO.FileExists(pthPath) Then
            Set ts = oFSO.OpenTextFile(pthPath, 1, False, 0)
            content = ts.ReadAll : ts.Close
            content = Replace(content, "#import site", "import site")
            If InStr(content, "Lib\site-packages") = 0 Then
                content = content & vbCrLf & "Lib" & vbCrLf & "Lib\site-packages" & vbCrLf
            End If
            Set tw = oFSO.OpenTextFile(pthPath, 2, True, 0)
            tw.Write content : tw.Close
        End If
    Next
    On Error GoTo 0
End Sub

Sub InstallPackages(pyDir, pkgDir)
    On Error Resume Next
    Dim pyExe  : pyExe  = pyDir & "\python.exe"
    Dim pipExe : pipExe = pyDir & "\Scripts\pip.exe"

    ' Use pip.exe if available, otherwise python -m pip
    Dim pipCmd
    If oFSO.FileExists(pipExe) Then
        pipCmd = """" & pipExe & """"
    Else
        pipCmd = """" & pyExe & """ -m pip"
    End If

    Dim findLinks : findLinks = "--no-index --find-links=""" & pkgDir & """"
    Dim quiet     : quiet     = "--no-warn-script-location --quiet"

    ' Install each package
    Dim pkgs(5)
    pkgs(0) = "shiboken6"
    pkgs(1) = "numpy"
    pkgs(2) = "pandas"
    pkgs(3) = "SQLAlchemy"
    pkgs(4) = "requests"
    pkgs(5) = "PySide6"

    Dim i
    For i = 0 To 5
        ShowStep "Installing " & pkgs(i) & "  (" & (i+1) & "/6)..."
        RunHidden pipCmd & " install " & findLinks & " " & quiet & " " & pkgs(i)
    Next
    On Error GoTo 0
End Sub

Sub WriteLauncher(installDir, pyDir, appDir)
    On Error Resume Next
    Dim path : path = installDir & "\NiftyTrader.vbs"
    Dim ts   : Set ts = oFSO.OpenTextFile(path, 2, True, 0)
    ts.WriteLine "' NiftyTrader Launcher — no console window"
    ts.WriteLine "Dim oShell : Set oShell = CreateObject(""WScript.Shell"")"
    ts.WriteLine "oShell.CurrentDirectory = """ & appDir & """"
    ts.WriteLine "Dim cmd : cmd = """ & Chr(34) & pyDir & "\python.exe" & Chr(34) & " " & Chr(34) & appDir & "\main.py" & Chr(34) & """"
    ts.WriteLine "oShell.Run cmd, 0, False"
    ts.Close
    On Error GoTo 0
End Sub

Sub WriteUninstaller(installDir, pyDir)
    On Error Resume Next
    Dim path : path = installDir & "\Uninstall.vbs"
    Dim ts   : Set ts = oFSO.OpenTextFile(path, 2, True, 0)
    ts.WriteLine "Option Explicit"
    ts.WriteLine "Dim oFSO, oWS, ans"
    ts.WriteLine "Set oFSO = CreateObject(""Scripting.FileSystemObject"")"
    ts.WriteLine "Set oWS  = CreateObject(""WScript.Shell"")"
    ts.WriteLine "ans = MsgBox(""Remove NiftyTrader from this computer?"",vbYesNo+vbQuestion,""Uninstall"")"
    ts.WriteLine "If ans = vbNo Then WScript.Quit"
    ts.WriteLine "Dim desk : desk = oWS.SpecialFolders(""Desktop"")"
    ts.WriteLine "If oFSO.FileExists(desk & ""\NiftyTrader.lnk"") Then oFSO.DeleteFile desk & ""\NiftyTrader.lnk"",True"
    ts.WriteLine "Dim sm : sm = oWS.SpecialFolders(""StartMenu"") & ""\Programs\NiftyTrader"""
    ts.WriteLine "If oFSO.FolderExists(sm) Then oFSO.DeleteFolder sm,True"
    ts.WriteLine "If oFSO.FolderExists(""" & installDir & """) Then oFSO.DeleteFolder """ & installDir & """,True"
    ts.WriteLine "MsgBox ""NiftyTrader has been removed."",vbInformation,""Done"""
    ts.Close
    On Error GoTo 0
End Sub

Sub MakeShortcut(lnkPath, target, args, workDir)
    On Error Resume Next
    Dim sc : Set sc = oWS.CreateShortcut(lnkPath)
    sc.TargetPath       = target
    sc.Arguments        = args
    sc.WorkingDirectory = workDir
    sc.Description      = "NiftyTrader Intelligence"
    sc.Save
    On Error GoTo 0
End Sub
