[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $InstallRoot,
    [Parameter(Mandatory = $true)] [string] $WheelRoot,
    [string] $PythonCommand = "py -3.12"
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath($InstallRoot)
$wheels = [IO.Path]::GetFullPath($WheelRoot)
if (!(Test-Path -LiteralPath $root)) { throw "安装目录不存在：$root" }
if (!(Test-Path -LiteralPath $wheels)) { throw "离线 wheel 目录不存在：$wheels" }

Push-Location $root
try {
    $venv = Join-Path $root ".venv"
    if (!(Test-Path -LiteralPath $venv)) {
        Invoke-Expression "$PythonCommand -m venv `"$venv`""
    }
    $python = Join-Path $venv "Scripts\python.exe"
    if (!(Test-Path -LiteralPath $python)) { throw "虚拟环境创建失败：$python" }
    & $python -m pip install --no-index --find-links $wheels --upgrade pip
    & $python -m pip install --no-index --find-links $wheels --upgrade clangwiki
    & $python -m clangwiki --version
    Write-Host "ClangWiki 已安装。请运行 scripts\Start-ClangWiki.ps1 启动本地服务。" -ForegroundColor Green
} finally { Pop-Location }
