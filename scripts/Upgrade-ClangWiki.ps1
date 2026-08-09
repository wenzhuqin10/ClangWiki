[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $InstallRoot,
    [Parameter(Mandatory = $true)] [string] $WheelRoot,
    [string] $DataRoot,
    [switch] $SkipBackup
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath($InstallRoot)
$wheels = [IO.Path]::GetFullPath($WheelRoot)
$python = Join-Path $root ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $python)) { throw "未找到已安装的虚拟环境：$python" }
if (!(Test-Path -LiteralPath $wheels)) { throw "离线 wheel 目录不存在：$wheels" }
if (!$SkipBackup -and $DataRoot) {
    $script = Join-Path $root "scripts\Backup-ClangWiki.ps1"
    if (Test-Path -LiteralPath $script) {
        & $script -DataRoot $DataRoot -Destination (Join-Path ([IO.Path]::GetDirectoryName($DataRoot)) "clangwiki-upgrade-backups")
    }
}
& $python -m pip install --no-index --find-links $wheels --upgrade clangwiki
& $python -m clangwiki --version
Write-Host "程序已升级。首次启动会自动执行数据库迁移；请保留升级前备份。" -ForegroundColor Green
