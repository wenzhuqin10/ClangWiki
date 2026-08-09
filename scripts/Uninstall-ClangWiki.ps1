[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [Parameter(Mandatory = $true)] [string] $InstallRoot,
    [switch] $RemoveData,
    [string] $DataRoot
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath($InstallRoot)
$venv = Join-Path $root ".venv"
if (Test-Path -LiteralPath $venv) {
    if ($PSCmdlet.ShouldProcess($venv, "删除 ClangWiki 虚拟环境")) { Remove-Item -LiteralPath $venv -Recurse -Force }
}
if ($RemoveData) {
    if ([string]::IsNullOrWhiteSpace($DataRoot)) { throw "指定 -RemoveData 时必须同时提供 -DataRoot。" }
    $data = [IO.Path]::GetFullPath($DataRoot)
    if ((Split-Path -Parent $data) -eq $data) { throw "拒绝删除磁盘根目录。" }
    if (Test-Path -LiteralPath $data) {
        if ($PSCmdlet.ShouldProcess($data, "删除 ClangWiki 数据根目录")) { Remove-Item -LiteralPath $data -Recurse -Force }
    }
}
Write-Host "已卸载本地运行环境。源码和未指定的数据目录不会被删除。" -ForegroundColor Yellow
