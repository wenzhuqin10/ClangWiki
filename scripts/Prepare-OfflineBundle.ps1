[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $ProjectRoot,
    [Parameter(Mandatory = $true)] [string] $OutputRoot,
    [string] $PythonCommand = "py -3.12",
    [switch] $IncludeRag,
    [string] $BgeModelRoot
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
        Invoke-Expression "$PythonCommand -m pip download --dest `"$wheels`" numpy usearch onnxruntime transformers"
        if ([string]::IsNullOrWhiteSpace($BgeModelRoot)) { throw "IncludeRag requires -BgeModelRoot pointing to the complete bge-m3 directory." }
        $model = [IO.Path]::GetFullPath($BgeModelRoot)
        if (!(Test-Path -LiteralPath (Join-Path $model "onnx\model.onnx"))) { throw "BGE-M3 ONNX model was not found: $model" }
        New-Item -ItemType Directory -Force -Path (Join-Path $output "models") | Out-Null
        Copy-Item -LiteralPath $model -Destination (Join-Path $output "models\bge-m3") -Recurse -Force
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
