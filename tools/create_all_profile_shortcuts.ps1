$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [System.Environment]::GetFolderPath('Desktop')

$profiles = @(2, 3, 4, 5)

foreach ($p in $profiles) {
    $ShortcutPath = Join-Path -Path $DesktopPath -ChildPath "Open Chrome Profile $p.lnk"
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = "D:\VibeCoding\recap_comics-master_V2\recap_comics-master\open_profile_$p.bat"
    $Shortcut.WorkingDirectory = "D:\VibeCoding\recap_comics-master_V2\recap_comics-master"
    $Shortcut.Description = "Open Chrome Profile $p directly"
    $Shortcut.IconLocation = "shell32.dll,220"
    $Shortcut.Save()
    Write-Host "Created shortcut: Open Chrome Profile $p.lnk"
}
