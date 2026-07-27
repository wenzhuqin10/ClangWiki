param(
  [string]$Source = (Join-Path $PSScriptRoot "..\clang-tool"),
  [string]$Build = (Join-Path $PSScriptRoot "..\build\clang-tool"),
  [string]$Install = (Join-Path $PSScriptRoot "..\bin")
)

$ErrorActionPreference = "Stop"
cmake -S $Source -B $Build
cmake --build $Build --config Release
New-Item -ItemType Directory -Force -Path $Install | Out-Null
$candidate = Get-ChildItem -Path $Build -Recurse -Filter "clangwiki-analyzer.exe" | Select-Object -First 1
if (-not $candidate) { throw "clangwiki-analyzer.exe was not produced." }
Copy-Item -LiteralPath $candidate.FullName -Destination (Join-Path $Install "clangwiki-analyzer.exe") -Force
Write-Host "Installed: $(Join-Path $Install 'clangwiki-analyzer.exe')"

