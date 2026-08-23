param(
    [Parameter(Mandatory = $true)]
    [string]$CertificateThumbprint,
    [string]$ExePath = ".\dist\touhou.exe",
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$resolvedExe = (Resolve-Path -LiteralPath $ExePath).Path
$certificate = Get-ChildItem -Path Cert:\CurrentUser\My, Cert:\LocalMachine\My |
    Where-Object { $_.Thumbprint -eq $CertificateThumbprint } |
    Select-Object -First 1
if (-not $certificate) {
    throw "未找到指定代码签名证书"
}

$signature = Set-AuthenticodeSignature `
    -FilePath $resolvedExe `
    -Certificate $certificate `
    -HashAlgorithm SHA256 `
    -TimestampServer $TimestampUrl
if ($signature.Status -ne "Valid") {
    throw "签名失败：$($signature.Status) $($signature.StatusMessage)"
}

$verified = Get-AuthenticodeSignature -FilePath $resolvedExe
[pscustomobject]@{
    status = $verified.Status.ToString()
    subject = $verified.SignerCertificate.Subject
    thumbprint = $verified.SignerCertificate.Thumbprint
    executable = $resolvedExe
} | ConvertTo-Json
