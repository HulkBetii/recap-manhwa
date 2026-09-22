$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [System.Environment]::GetFolderPath('Desktop')

# 1. Shortcut: Login Chrome Profiles Manager
$ShortcutPath1 = Join-Path -Path $DesktopPath -ChildPath "Login Chrome Profiles.lnk"
$Shortcut1 = $WshShell.CreateShortcut($ShortcutPath1)
$Shortcut1.TargetPath = "D:\VibeCoding\recap_comics-master_V2\recap_comics-master\login_profiles.bat"
$Shortcut1.WorkingDirectory = "D:\VibeCoding\recap_comics-master_V2\recap_comics-master"
$Shortcut1.Description = "Chrome Profiles Login / Setup Helper"
$Shortcut1.IconLocation = "shell32.dll,14"
$Shortcut1.Save()

# 2. Shortcut: Open Profile 1
$ShortcutPath2 = Join-Path -Path $DesktopPath -ChildPath "Open Chrome Profile 1.lnk"
$Shortcut2 = $WshShell.CreateShortcut($ShortcutPath2)
$Shortcut2.TargetPath = "D:\VibeCoding\recap_comics-master_V2\recap_comics-master\open_profile_1.bat"
$Shortcut2.WorkingDirectory = "D:\VibeCoding\recap_comics-master_V2\recap_comics-master"
$Shortcut2.Description = "Open Chrome Profile 1 directly"
$Shortcut2.IconLocation = "shell32.dll,220"
$Shortcut2.Save()

Write-Host "Created shortcuts on Desktop."
