[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $ProjectRoot,
    [Parameter(Mandatory = $true)] [string] $OutputRoot,
    [string] $PythonCommand = "py -3.12",
    [switch] $IncludeRag
)

$ErrorActionPreference = "Stop"
$project = [IO.Path]::GetFullPath($ProjectRoot)
$output = [IO.Path]::GetFullPath($OutputRoot)
if (!(Test-Path -LiteralPath (Join-Path $project "pyproject.toml"))) { throw "未找到 pyproject.toml：$project" }
New-Item -ItemType Directory -Force -Path $output | Out-Null
$wheels = Join-Path $output "wheels"
New-Item -ItemType Directory -Force -Path $wheels | Out-Null

Push-Location $project
try {
    Invoke-Expression "$PythonCommand -m pip wheel --wheel-dir `"$wheels`" ."
    Invoke-Expression "$PythonCommand -m pip download --dest `"$wheels`" fastapi pydantic uvicorn httpx"
    if ($IncludeRag) {
        Invoke-Expression "$PythonCommand -m pip download --dest `"$wheels`" fastembed numpy usearch"
    }
    $manifest = Join-Path $output "SHA256SUMS.txt"
    Get-ChildItem -LiteralPath $output -Recurse -File |
        Where-Object { $_.FullName -ne $manifest } |
        ForEach-Object {
            $relative = $_.FullName.Substring($output.Length).TrimStart('\')
            "{0}  {1}" -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(), $relative
        } | Set-Content -LiteralPath $manifest -Encoding utf8
    Write-Host "离线交付包已准备：$output" -ForegroundColor Green
} finally { Pop-Location }
