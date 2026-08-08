param(
  [string]$Source = (Join-Path $PSScriptRoot "..\clang-tool"),
  [string]$Build = (Join-Path $PSScriptRoot "..\build\clang-tool-libclang"),
  [string]$Install = (Join-Path $PSScriptRoot "..\bin"),
  [string]$LLVMRoot = $(if ($env:LLVM_ROOT) { $env:LLVM_ROOT } else { "C:\Program Files\LLVM" })
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path (Join-Path $LLVMRoot "include\clang-c\Index.h"))) {
  throw "libclang headers were not found under '$LLVMRoot'. Pass -LLVMRoot with the LLVM installation path."
}
if (-not (Test-Path (Join-Path $LLVMRoot "lib\libclang.lib"))) {
  throw "libclang.lib was not found under '$LLVMRoot'."
}

cmake -S $Source -B $Build -G "Visual Studio 17 2022" -A x64 "-DLLVM_ROOT=$LLVMRoot"
cmake --build $Build --config Release
New-Item -ItemType Directory -Force -Path $Install | Out-Null
$candidate = Get-ChildItem -Path $Build -Recurse -Filter "clangwiki-analyzer.exe" | Select-Object -First 1
if (-not $candidate) { throw "clangwiki-analyzer.exe was not produced." }
Copy-Item -LiteralPath $candidate.FullName -Destination (Join-Path $Install "clangwiki-analyzer.exe") -Force
$runtime = Join-Path $LLVMRoot "bin\libclang.dll"
if (Test-Path $runtime) {
  Copy-Item -LiteralPath $runtime -Destination (Join-Path $Install "libclang.dll") -Force
}
Write-Host "Installed: $(Join-Path $Install 'clangwiki-analyzer.exe')"
