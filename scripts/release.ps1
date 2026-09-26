param(
    [ValidateSet('Status', 'Exe', 'Package')]
    [string]$Mode = 'Status',
    [string]$CertificateThumbprint = ''
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Prefix = $ProjectRoot.TrimEnd('\') + '\'
$CandidateZip = Join-Path $ProjectRoot ('release\touhou-test-package.' + [guid]::NewGuid().ToString('N') + '.candidate.zip')
$CandidateExe = Join-Path $ProjectRoot ('touhou.' + [guid]::NewGuid().ToString('N') + '.candidate.exe')

function Assert-WorkspaceFile([string]$Path) {
    $Full = [IO.Path]::GetFullPath($Path)
    if (-not $Full.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Release path escaped workspace' }
    if (Test-Path -LiteralPath $Full) {
        $Item = Get-Item -LiteralPath $Full
        if ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Release target must not be a link' }
    }
}

function Publish-File([string]$Source, [string]$Destination) {
    Assert-WorkspaceFile $Source
    Assert-WorkspaceFile $Destination
    if (Test-Path -LiteralPath $Destination) { [IO.File]::Replace($Source, $Destination, $null) }
    else { [IO.File]::Move($Source, $Destination) }
}

Push-Location $ProjectRoot
try {
    if ($Mode -eq 'Status') {
        & python release_status.py
        if ($LASTEXITCODE -ne 0) { throw 'Release inventory failed' }
        return
    }
    & npm run quality
    if ($LASTEXITCODE -ne 0) { throw 'Quality gate failed' }
    & npm run test:e2e
    if ($LASTEXITCODE -ne 0) { throw 'Browser regression failed' }
    & (Join-Path $PSScriptRoot 'sync-release-worlds.ps1')
    & python -m PyInstaller --noconfirm --clean api_release.spec
    if ($LASTEXITCODE -ne 0) { throw 'Executable build failed' }
    if ($CertificateThumbprint) {
        & (Join-Path $PSScriptRoot 'sign-release.ps1') -CertificateThumbprint $CertificateThumbprint -ExePath '.\dist\touhou.exe'
    }
    & (Join-Path $PSScriptRoot 'smoke-exe.ps1') -ExePath '.\dist\touhou.exe'
    Copy-Item -LiteralPath '.\dist\touhou.exe' -Destination $CandidateExe
    Publish-File $CandidateExe (Join-Path $ProjectRoot 'touhou.exe')
    if ($Mode -eq 'Package') {
        $RelativeZip = $CandidateZip.Substring($Prefix.Length)
        & (Join-Path $PSScriptRoot 'package-test.ps1') -OutputPath $RelativeZip
        & (Join-Path $PSScriptRoot 'verify-test-package.ps1') -ZipPath $RelativeZip
        $FinalZip = Join-Path $ProjectRoot 'release\touhou-test-package.zip'
        Publish-File $CandidateZip $FinalZip
        & python release_manifest.py --root release --output ($FinalZip + '.manifest.json') $FinalZip
        if ($LASTEXITCODE -ne 0) { throw 'Published package manifest failed' }
    } else {
        Write-Host 'EXE updated. The existing ZIP was not rebuilt; see the independent ZIP status below.'
    }
} finally {
    foreach ($Path in @($CandidateExe, $CandidateZip, ($CandidateZip + '.manifest.json'))) {
        Assert-WorkspaceFile $Path
        if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Force }
    }
    if ($Mode -ne 'Status') {
        & python release_status.py --output release/artifact-status.json
        if ($LASTEXITCODE -ne 0) { Write-Warning 'Could not refresh release inventory.' }
    }
    Pop-Location
}
