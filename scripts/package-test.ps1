param(
    [string]$OutputPath = "release\touhou-test-package.zip"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Output = Join-Path $ProjectRoot $OutputPath
$Staging = Join-Path ([System.IO.Path]::GetTempPath()) ("touhou-package-" + [guid]::NewGuid().ToString("N"))

try {
    New-Item -ItemType Directory -Path $Staging | Out-Null
    foreach ($Name in @("touhou.exe", "启动touhou.bat", "停止服务.bat", "玩前必读.txt")) {
        $Source = Join-Path $ProjectRoot $Name
        if (Test-Path -LiteralPath $Source) {
            Copy-Item -LiteralPath $Source -Destination $Staging
        }
    }
    Set-Content -LiteralPath (Join-Path $Staging ".env") -Value @(
        "DEEPSEEK_API_KEY="
        "DEEPSEEK_MODEL=deepseek-v4-flash"
    ) -Encoding UTF8

    $OutputDirectory = Split-Path -Parent $Output
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    if (Test-Path -LiteralPath $Output) {
        Remove-Item -LiteralPath $Output
    }
    Compress-Archive -Path (Join-Path $Staging "*") -DestinationPath $Output -CompressionLevel Optimal
    Write-Host "Created clean test package: $Output"
} finally {
    if (Test-Path -LiteralPath $Staging) {
        $ResolvedStaging = (Resolve-Path -LiteralPath $Staging).Path
        $ResolvedTemp = (Resolve-Path -LiteralPath ([System.IO.Path]::GetTempPath())).Path
        if ($ResolvedStaging.StartsWith($ResolvedTemp, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $ResolvedStaging -Recurse -Force
        }
    }
}
