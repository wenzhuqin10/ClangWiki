# Run this file from an elevated PowerShell window. A reboot may be required.
$ErrorActionPreference = "Stop"
wsl.exe --install -d Ubuntu-24.04
Write-Host "Restart Windows if requested. After Ubuntu initialization, copy this repository inside ~/projects and run scripts/bootstrap-wsl.sh."
