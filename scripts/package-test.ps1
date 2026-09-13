param(
    [string]$OutputPath = "release\touhou-test-package.zip"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Output = Join-Path $ProjectRoot $OutputPath
$Staging = Join-Path ([System.IO.Path]::GetTempPath()) ("touhou-package-" + [guid]::NewGuid().ToString("N"))
$Verified = Get-Content -LiteralPath (Join-Path $ProjectRoot "release\verified-exe.json") -Raw | ConvertFrom-Json
$Build = Get-Content -LiteralPath (Join-Path $ProjectRoot "release\build-info.json") -Raw | ConvertFrom-Json
$CurrentBuild = & python (Join-Path $ProjectRoot "build_identity.py")
if ($LASTEXITCODE -ne 0 -or $CurrentBuild.Trim() -ne $Build.build_id) { throw "Release inputs changed after verification" }
if ($Verified.build_id -ne $Build.build_id -or (Get-FileHash -LiteralPath (Join-Path $ProjectRoot "touhou.exe") -Algorithm SHA256).Hash -ne $Verified.sha256) {
    throw "Root executable has not passed the current build smoke test."
}

try {
    New-Item -ItemType Directory -Path $Staging | Out-Null
    foreach ($Name in @("touhou.exe", "启动touhou.bat", "停止服务.bat", "玩前必读.txt")) {
        $Source = Join-Path $ProjectRoot $Name
        if (-not (Test-Path -LiteralPath $Source)) { throw "Missing release file: $Name" }
        Copy-Item -LiteralPath $Source -Destination $Staging
    }
    Set-Content -LiteralPath (Join-Path $Staging ".env") -Value @(
        "DEEPSEEK_API_KEY="
        "DEEPSEEK_BASE_URL=https://api.deepseek.com"
        "DEEPSEEK_MODEL=deepseek-v4-flash"
        "TOUHOU_AI_MODELS=deepseek-v4-flash,deepseek-v4-pro"
    ) -Encoding UTF8

    & python (Join-Path $ProjectRoot "release_manifest.py") `
        --root $Staging `
        --output (Join-Path $Staging "release-manifest.json")
    if ($LASTEXITCODE -ne 0) {
        throw "Release manifest generation failed."
    }

    $OutputDirectory = Split-Path -Parent $Output
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    if (Test-Path -LiteralPath $Output) {
        Remove-Item -LiteralPath $Output
    }
    Compress-Archive -Path (Join-Path $Staging "*") -DestinationPath $Output -CompressionLevel Optimal
    & python (Join-Path $ProjectRoot "release_manifest.py") `
        --root $OutputDirectory `
        --output ($Output + ".manifest.json") `
        $Output
    if ($LASTEXITCODE -ne 0) {
        throw "Package checksum manifest generation failed."
    }
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
