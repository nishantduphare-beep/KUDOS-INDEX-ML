' NiftyTrader Intelligence — Launcher
' No console window, no admin rights needed.
Dim oShell, oFSO
Set oShell = CreateObject("WScript.Shell")
Set oFSO   = CreateObject("Scripting.FileSystemObject")

Dim appData    : appData    = oShell.ExpandEnvironmentStrings("%LOCALAPPDATA%")
Dim installDir : installDir = appData & "\NiftyTrader"
Dim pyExe      : pyExe      = installDir & "\python\python.exe"
Dim appMain    : appMain    = installDir & "\app\main.py"

If Not oFSO.FileExists(pyExe) Then
    MsgBox "NiftyTrader is not installed." & vbCrLf & vbCrLf & _
           "Please run Install.vbs to install it first.", _
           vbCritical, "NiftyTrader"
    WScript.Quit
End If

oShell.CurrentDirectory = installDir & "\app"
oShell.Run """" & pyExe & """ """ & appMain & """", 0, False
