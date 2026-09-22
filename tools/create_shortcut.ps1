$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [System.Environment]::GetFolderPath('Desktop')
$ShortcutPath = Join-Path -Path $DesktopPath -ChildPath "Recap Manhwa Tool.lnk"
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = "D:\VibeCoding\recap_comics-master_V2\recap_comics-master\start_tool.bat"
$Shortcut.WorkingDirectory = "D:\VibeCoding\recap_comics-master_V2\recap_comics-master"
$Shortcut.Description = "Recap Manhwa Automation Tool v2.0"
$Shortcut.IconLocation = "shell32.dll,220"
$Shortcut.Save()
Write-Host "Shortcut created successfully at: $ShortcutPath"
