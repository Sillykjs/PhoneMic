$ProjectRoot = $PSScriptRoot

$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "PhoneMic.lnk"

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath       = "$ProjectRoot\.venv\Scripts\pythonw.exe"
# launch.pyw 先钉住系统 icuuc.dll 再启动程序，避免双击启动时 Qt 绑定到
# Anaconda 的 ICU 而弹出「无法定位程序输入点」对话框。
$Shortcut.Arguments        = """$ProjectRoot\launch.pyw"""
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.Description      = "PhoneMic (from source)"
$Shortcut.IconLocation     = "$ProjectRoot\phonemic\resources\favicon.ico,0"
$Shortcut.Save()

Write-Host "Shortcut created: $ShortcutPath"