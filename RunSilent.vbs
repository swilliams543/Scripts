' This script silently runs scripts by specifying program path and script path for execution, without opening a command prompt window

Set WshShell = CreateObject("WScript.Shell")
Dim programPath, scriptPath
programPath = WScript.Arguments(0)
scriptPath = WScript.Arguments(1)

WshShell.Run """" & programPath & """ """ & scriptPath & """", 0, False