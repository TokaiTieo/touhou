param(
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$sourceRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "worlds"))
$sourcePrefix = $sourceRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
$releaseRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot "release"))
$targetRoot = if ($Target) {
    [IO.Path]::GetFullPath($Target)
} else {
    [IO.Path]::GetFullPath((Join-Path $releaseRoot "build_worlds_clean"))
}

$releasePrefix = $releaseRoot.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $targetRoot.StartsWith($releasePrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Release world target must stay inside $releaseRoot"
}

if (Test-Path -LiteralPath $targetRoot) {
    Remove-Item -LiteralPath $targetRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $targetRoot -Force | Out-Null

$sessionSegment = "world_touhou" + [IO.Path]::DirectorySeparatorChar + "sessions" + [IO.Path]::DirectorySeparatorChar
Get-ChildItem -LiteralPath $sourceRoot -File -Recurse | ForEach-Object {
    if (-not $_.FullName.StartsWith($sourcePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Source file escaped worlds directory."
    }
    $relative = $_.FullName.Substring($sourcePrefix.Length)
    if ($relative.StartsWith($sessionSegment, [StringComparison]::OrdinalIgnoreCase)) {
        return
    }
    $destination = Join-Path $targetRoot $relative
    $destinationParent = Split-Path -Parent $destination
    New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $destination -Force
}

New-Item -ItemType Directory -Path (Join-Path $targetRoot "world_touhou\sessions\characters") -Force | Out-Null

$files = Get-ChildItem -LiteralPath $targetRoot -File -Recurse
$saveFiles = $files | Where-Object {
    $_.FullName -like "*\sessions\characters\*.json"
}
if ($saveFiles) {
    throw "Clean release worlds unexpectedly contain character saves."
}

[pscustomobject]@{
    status = "ok"
    target = $targetRoot
    files = $files.Count
    character_saves = 0
} | ConvertTo-Json
