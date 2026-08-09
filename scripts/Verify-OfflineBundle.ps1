[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $BundleRoot,
    [string] $Manifest = "SHA256SUMS.txt"
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath($BundleRoot)
$manifestPath = Join-Path $root $Manifest
if (!(Test-Path -LiteralPath $manifestPath)) { throw "未找到校验清单：$manifestPath" }
$failed = 0
Get-Content -LiteralPath $manifestPath | ForEach-Object {
    if ([string]::IsNullOrWhiteSpace($_) -or $_.StartsWith("#")) { return }
    $parts = $_ -split "\s+", 2
    if ($parts.Count -ne 2) { throw "校验清单行格式错误：$_" }
    $path = Join-Path $root $parts[1].Trim()
    if (!(Test-Path -LiteralPath $path)) { Write-Error "缺少文件：$path"; $failed++; return }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $parts[0].ToLowerInvariant()) { Write-Error "哈希不匹配：$path"; $failed++ }
}
if ($failed -gt 0) { throw "离线包校验失败：$failed 个文件异常。" }
Write-Host "离线包校验通过。" -ForegroundColor Green
