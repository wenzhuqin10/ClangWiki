[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $DataRoot,
    [Parameter(Mandatory = $true)] [string] $Destination
)

$ErrorActionPreference = "Stop"
$source = [IO.Path]::GetFullPath($DataRoot)
$target = [IO.Path]::GetFullPath($Destination)
if (!(Test-Path -LiteralPath $source)) { throw "数据根目录不存在：$source" }
New-Item -ItemType Directory -Force -Path $target | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$archive = Join-Path $target "clangwiki-data-$stamp.zip"
Compress-Archive -LiteralPath $source -DestinationPath $archive -CompressionLevel Optimal
Write-Host "已创建备份：$archive" -ForegroundColor Green
