$ErrorActionPreference = 'Stop'

function Invoke-CheckedProcess([string]$File, [string[]]$Arguments) {
    $process = Start-Process -FilePath $File -ArgumentList $Arguments -WindowStyle Hidden -PassThru
    if (!$process.WaitForExit(60000)) {
        $process.Kill()
        throw "Smoke process timed out: $File"
    }
    if ($process.ExitCode -ne 0) { throw "Smoke process failed ($($process.ExitCode)): $File" }
}

function Test-SmokeResult([string]$Path, [string]$Version) {
    $deadline = [DateTime]::UtcNow.AddSeconds(60)
    while (!(Test-Path -LiteralPath $Path) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 100 }
    if (!(Test-Path -LiteralPath $Path)) { throw "Missing smoke result: $Path" }
    $result = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if (!$result.frozen -or !$result.resources_ok -or !$result.pdf_render_ok -or !$result.ocr_ok -or
        $result.qt_platform -ne 'windows' -or $result.version -ne $Version) {
        throw "Invalid smoke result: $($result | ConvertTo-Json -Compress)"
    }
}

$portable = Get-Item -LiteralPath release/OmniPDF-windows-x64.exe
$version = $portable.VersionInfo.ProductVersion.Trim()
$digest = (Get-FileHash -LiteralPath $portable.FullName).Hash
$tempRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$trial = (New-Item -ItemType Directory -Path (Join-Path $tempRoot ('omnipdf-smoke-' + [guid]::NewGuid().ToString('N')))).FullName
$normalOutput = Join-Path $trial 'portable.json'
$updatedOutput = Join-Path $trial 'updated.json'
$target = Join-Path $trial 'Renamed Omni PDF.exe'
try {
    Invoke-CheckedProcess -File $portable.FullName -Arguments @('--smoke-test', '--output', ('"' + $normalOutput + '"'))
    Test-SmokeResult $normalOutput $version

    Set-Content -LiteralPath $target -Value 'previous executable fixture' -Encoding ascii
    $shell = (Get-Process -Id $PID).Path
    $holder = Start-Process -FilePath $shell -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep -Seconds 2') -WindowStyle Hidden -PassThru
    Invoke-CheckedProcess -File $portable.FullName -Arguments @('--apply-portable-update',
        ('"' + $target + '"'), [string]$holder.Id, $version, $digest, [string]$portable.Length,
        '--smoke-test', '--output', ('"' + $updatedOutput + '"'))
    if (!$holder.HasExited -or $holder.ExitCode -ne 0) { throw 'Portable updater did not allow the app to exit normally' }
    Test-SmokeResult $updatedOutput $version
    if ((Get-FileHash -LiteralPath $target).Hash -ne $digest) { throw 'The updated EXE differs from the release asset' }
} finally {
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        $running = @(Get-Process -Name 'Renamed Omni PDF' -ErrorAction SilentlyContinue | Where-Object Path -eq $target)
        if (!$running) { break }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    if (!$running) {
        Remove-Item -LiteralPath $normalOutput, $updatedOutput, $target -ErrorAction SilentlyContinue
        if (!(Get-ChildItem -LiteralPath $trial -Force | Select-Object -First 1)) {
            Remove-Item -LiteralPath $trial
        }
    }
}
