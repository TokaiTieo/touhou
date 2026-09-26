param([string]$ZipPath = "release\touhou-test-package.zip")

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Zip = (Resolve-Path -LiteralPath (Join-Path $ProjectRoot $ZipPath)).Path
$TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
$Extract = [IO.Path]::GetFullPath((Join-Path $TempRoot ("touhou-zip-verify-" + [guid]::NewGuid().ToString('N'))))
if (-not $Extract.StartsWith($TempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "Invalid verification directory" }
$Allowed = @('touhou.exe', '启动touhou.bat', '停止服务.bat', '玩前必读.txt', '.env', 'release-manifest.json')
Add-Type -AssemblyName System.IO.Compression.FileSystem
$Archive = [IO.Compression.ZipFile]::OpenRead($Zip)
try {
    $Names = @($Archive.Entries | ForEach-Object { $_.FullName })
    if ($Names.Count -ne $Allowed.Count -or @($Names | Sort-Object -Unique).Count -ne $Allowed.Count) { throw "Unexpected package entry count" }
    foreach ($Name in $Names) {
        if ($Name -cnotin $Allowed) { throw "Unexpected package entry: $Name" }
    }
} finally { $Archive.Dispose() }
try {
    Expand-Archive -LiteralPath $Zip -DestinationPath $Extract
    $Manifest = Get-Content -LiteralPath (Join-Path $Extract 'release-manifest.json') -Raw | ConvertFrom-Json
    $Build = Get-Content -LiteralPath (Join-Path $ProjectRoot 'release\build-info.json') -Raw | ConvertFrom-Json
    if ($Manifest.build_id -ne $Build.build_id) { throw "ZIP manifest build identity mismatch" }
    foreach ($File in $Manifest.files) {
        if ($File.path -cnotin $Allowed) { throw "Unexpected manifest path" }
        $Hash = (Get-FileHash -LiteralPath (Join-Path $Extract $File.path) -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($Hash -ne $File.sha256) { throw "ZIP entry hash mismatch: $($File.path)" }
    }
    $EnvLines = Get-Content -LiteralPath (Join-Path $Extract '.env')
    if (@($EnvLines | Where-Object { $_ -match '^DEEPSEEK_API_KEY=\s*$' }).Count -ne 1) { throw "Package Key is not blank" }
    & (Join-Path $PSScriptRoot 'smoke-exe.ps1') -ExePath (Join-Path $Extract 'touhou.exe')
    [pscustomobject]@{
        build_id = $Build.build_id
        version = $Build.version
        sha256 = (Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $ProjectRoot 'release\verified-package.json') -Encoding UTF8
    Write-Host 'ZIP whitelist, blank Key, checksums and extracted executable smoke passed.'
} finally {
    if (Test-Path -LiteralPath $Extract) {
        $Resolved = (Resolve-Path -LiteralPath $Extract).Path
        if (-not $Resolved.StartsWith($TempRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "Cleanup path escaped verification directory" }
        Remove-Item -LiteralPath $Resolved -Recurse -Force
    }
}
