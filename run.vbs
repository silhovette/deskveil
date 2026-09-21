Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
folder = fs.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = folder
python = folder & "\.venv\Scripts\pythonw.exe"
If fs.FileExists(python) Then
    shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & folder & "\main.py" & Chr(34), 0, False
Else
    MsgBox "Create the Python environment first. See README.md.", 48, "DeskVeil"
End If
