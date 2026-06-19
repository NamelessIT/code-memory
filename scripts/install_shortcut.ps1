# Tao shortcut "code-memory" tren Desktop (icon) -> bam 1 cai la chay app + mo trinh duyet.
# Chay 1 lan:  powershell -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1
# Them -AutoStart de chay cung Windows.
param([switch]$AutoStart)

$root = Split-Path $PSScriptRoot -Parent
$vbs  = Join-Path $root "scripts\start_hidden.vbs"
$ws   = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')

function New-CMShortcut($path) {
    $lnk = $ws.CreateShortcut($path)
    $lnk.TargetPath = $vbs
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"  # icon san co cua Windows
    $lnk.Description = "code-memory - chat hoi dap codebase local"
    $lnk.Save()
}

$dlnk = Join-Path $desktop "code-memory.lnk"
New-CMShortcut $dlnk
Write-Host "[OK] Da tao icon tren Desktop: $dlnk"
Write-Host "     -> Double-click la mo app (chay nen) + tu mo trinh duyet."

if ($AutoStart) {
    $startup = [Environment]::GetFolderPath('Startup')
    New-CMShortcut (Join-Path $startup "code-memory.lnk")
    Write-Host "[OK] Da bat chay cung Windows (Startup)."
} else {
    Write-Host "     (Muon chay cung Windows: them tham so -AutoStart)"
}
