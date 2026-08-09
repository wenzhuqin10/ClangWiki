[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $InstallRoot,
    [Parameter(Mandatory = $true)] [string] $DataRoot,
    [ValidateRange(1024, 65535)] [int] $Port = 8082
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath($InstallRoot)
$data = [IO.Path]::GetFullPath($DataRoot)
$python = Join-Path $root ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $python)) { throw "未找到 ClangWiki 虚拟环境：$python" }
New-Item -ItemType Directory -Force -Path $data | Out-Null
Write-Host "ClangWiki 将只监听 http://127.0.0.1:$Port/" -ForegroundColor Cyan
& $python -m clangwiki --data-root $data serve --host 127.0.0.1 --port $Port
