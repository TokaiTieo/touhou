param(
    [Parameter(Mandatory = $false)]
    [string]$ExePath = ".\dist\touhou.exe"
)

$ErrorActionPreference = "Stop"
$resolvedExe = (Resolve-Path -LiteralPath $ExePath).Path
$smokeRoot = Join-Path $env:TEMP ("touhou-exe-smoke-" + [guid]::NewGuid().ToString("N"))
$previousDataDir = $env:TOUHOU_DATA_DIR
$previousSmokeFlag = $env:TOUHOU_SMOKE_TEST
$previousSmokeSeconds = $env:TOUHOU_SMOKE_SECONDS
$previousMockAI = $env:TOUHOU_E2E_MOCK_AI
$previousApiKey = $env:DEEPSEEK_API_KEY
$process = $null
$succeeded = $false

try {
    New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null
    $portProbe = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $portProbe.Start()
    $smokePort = $portProbe.LocalEndpoint.Port
    $portProbe.Stop()
    @"
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
APP_HOST=127.0.0.1
APP_PORT=$smokePort
APP_DEBUG=False
DEBUG=False
PRIVATE_DEBUG=False
"@ | Set-Content -LiteralPath (Join-Path $smokeRoot ".env") -Encoding UTF8
    $env:TOUHOU_DATA_DIR = $smokeRoot
    $env:TOUHOU_SMOKE_TEST = "1"
    $env:TOUHOU_SMOKE_SECONDS = "60"
    $env:TOUHOU_E2E_MOCK_AI = "1"
    $env:DEEPSEEK_API_KEY = "smoke-system-key-not-real"
    $process = Start-Process -FilePath $resolvedExe -PassThru -WindowStyle Hidden

    $runtimePath = Join-Path $smokeRoot "runtime.json"
    $deadline = [DateTime]::UtcNow.AddSeconds(75)
    $runtime = $null
    while (-not $runtime -or $runtime.status -ne "ready") {
        if ($process.HasExited) {
            throw "EXE exited before writing runtime.json (exit code $($process.ExitCode))."
        }
        if ([DateTime]::UtcNow -gt $deadline) {
            throw "Timed out waiting for runtime.json."
        }
        if (Test-Path -LiteralPath $runtimePath) {
            try {
                $runtime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
            } catch {
                $runtime = $null
            }
        }
        Start-Sleep -Milliseconds 250
    }

    if ($runtime.port -ne $smokePort) {
        throw "EXE did not use the isolated smoke-test port."
    }
    $health = $null
    while (-not $health) {
        if ($process.HasExited) {
            throw "EXE exited before its isolated health endpoint became ready (exit code $($process.ExitCode))."
        }
        if ([DateTime]::UtcNow -gt $deadline) {
            throw "Timed out waiting for the isolated health endpoint."
        }
        try {
            $health = Invoke-RestMethod -Uri ($runtime.url + "/api/health") -TimeoutSec 2
        } catch {
            Start-Sleep -Milliseconds 200
        }
    }
    $version = Invoke-RestMethod -Uri ($runtime.url + "/api/version") -TimeoutSec 10
    $index = Invoke-WebRequest -Uri ($runtime.url + "/") -UseBasicParsing -TimeoutSec 10

    if ($health.status -ne "ok") {
        throw "Health endpoint returned an unexpected status."
    }
    if ($index.Content -notmatch "<title>TouHou") {
        throw "Bundled index page did not contain the TouHou title."
    }
    if ($index.Content -notmatch 'meta name="touhou-session-token" content="([^"]+)"') {
        throw "Bundled index page did not expose a local session token."
    }

    $headers = @{ "X-Touhou-Token" = $Matches[1] }
    $keyStatus = Invoke-RestMethod -Uri ($runtime.url + "/api/ghost/get_api_key") -Headers $headers -TimeoutSec 10
    if (-not $keyStatus.has_key -or $keyStatus.key_source -ne "system_environment") {
        throw "Packaged API Key environment fallback validation failed."
    }
    if (($keyStatus | ConvertTo-Json -Compress) -match "smoke-system-key-not-real") {
        throw "Packaged API Key status exposed the complete credential."
    }
    if (Test-Path -LiteralPath (Join-Path $smokeRoot "config\api_key.dat")) {
        throw "System environment API Key was unexpectedly persisted."
    }
    $character = Invoke-RestMethod -Method Post `
        -Uri ($runtime.url + "/api/ghost/create_character") `
        -Headers $headers `
        -ContentType "application/json; charset=utf-8" `
        -Body (@{
            profile = @{
                name = "打包验证者"
                gender = "女"
                identity = "幻想乡原住民"
                appearance = "普通"
                personality = "谨慎"
                background = "居住在人间之里"
            }
        } | ConvertTo-Json -Depth 5) `
        -TimeoutSec 20
    $turnBody = @{
        character_id = $character.character_id
        scene = "博丽神社"
        player_name = "打包验证者"
        user_input = @{ action = "调查结界"; speech = "" }
        history = @()
        scene_npcs = @()
        turn_id = "packaged-langgraph-smoke"
    } | ConvertTo-Json -Depth 5
    $turn = Invoke-RestMethod -Method Post `
        -Uri ($runtime.url + "/api/ghost/environment_interact") `
        -Headers $headers `
        -ContentType "application/json; charset=utf-8" `
        -Body $turnBody `
        -TimeoutSec 30
    $duplicateTurn = Invoke-RestMethod -Method Post `
        -Uri ($runtime.url + "/api/ghost/environment_interact") `
        -Headers $headers `
        -ContentType "application/json; charset=utf-8" `
        -Body $turnBody `
        -TimeoutSec 30
    if (-not $turn.description -or $turn.description -ne $duplicateTurn.description) {
        throw "Packaged LangGraph turn or duplicate receipt validation failed."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $smokeRoot "runtime\turn_checkpoints.sqlite3"))) {
        throw "Packaged LangGraph SQLite checkpoint was not created."
    }
    Invoke-RestMethod -Method Post -Uri ($runtime.url + "/api/shutdown") -Headers $headers -TimeoutSec 10 | Out-Null
    $shutdownDeadline = [DateTime]::UtcNow.AddSeconds(20)
    $serviceStopped = $false
    while ([DateTime]::UtcNow -lt $shutdownDeadline) {
        try {
            Invoke-RestMethod -Uri ($runtime.url + "/api/health") -TimeoutSec 1 | Out-Null
            Start-Sleep -Milliseconds 200
        } catch {
            $serviceStopped = $true
            break
        }
    }
    if (-not $serviceStopped) {
        throw "EXE health endpoint remained available after shutdown."
    }
    if (-not $process.HasExited) {
        taskkill /PID $process.Id /T /F 2>$null | Out-Null
        $process.WaitForExit(5000) | Out-Null
    }
    $succeeded = $true

    [pscustomobject]@{
        status = "ok"
        version = $version.display_version
        executable = $resolvedExe
        size_bytes = (Get-Item -LiteralPath $resolvedExe).Length
        isolated_port = $smokePort
        data_dir = "removed after successful verification"
    } | ConvertTo-Json -Depth 3
}
finally {
    if ($process -and -not $process.HasExited) {
        taskkill /PID $process.Id /T /F 2>$null | Out-Null
        $process.WaitForExit(5000) | Out-Null
    }
    $env:TOUHOU_DATA_DIR = $previousDataDir
    $env:TOUHOU_SMOKE_TEST = $previousSmokeFlag
    $env:TOUHOU_SMOKE_SECONDS = $previousSmokeSeconds
    $env:TOUHOU_E2E_MOCK_AI = $previousMockAI
    $env:DEEPSEEK_API_KEY = $previousApiKey
    if ($succeeded -and (Test-Path -LiteralPath $smokeRoot)) {
        $tempPrefix = [IO.Path]::GetFullPath($env:TEMP).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
        $resolvedSmokeRoot = [IO.Path]::GetFullPath($smokeRoot)
        if ($resolvedSmokeRoot.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolvedSmokeRoot -Recurse -Force
        }
    }
}
