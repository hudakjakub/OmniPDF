$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true') { throw 'Installer smoke tests require an isolated GitHub runner.' }

function Invoke-CheckedProcess([string]$File, [string[]]$Arguments) {
    $process = Start-Process -FilePath $File -ArgumentList $Arguments -WindowStyle Hidden -PassThru
    if (!$process.WaitForExit(45000)) {
        $process.Kill($true)
        throw "Smoke process timed out: $File"
    }
    if ($process.ExitCode -ne 0) { throw "Smoke process failed ($($process.ExitCode)): $File" }
}

function Test-SmokeResult([string]$Path) {
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    while (!(Test-Path -LiteralPath $Path) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 100 }
    if (!(Test-Path -LiteralPath $Path)) { throw "Missing smoke result: $Path" }
    $result = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if (!$result.frozen -or !$result.resources_ok -or !$result.pdf_render_ok -or !$result.ocr_ok -or $result.qt_platform -ne 'windows') {
        throw "Invalid smoke result: $($result | ConvertTo-Json -Compress)"
    }
}

$portable = Get-Item release/OmniPDF-windows-x64.exe
$setup = Get-Item release/OmniPDF-Setup-windows-x64.exe
$target = Join-Path $env:RUNNER_TEMP 'OmniPDF-test'
Get-Content release/SHA256SUMS.txt | ForEach-Object {
    $hash, $name = $_ -split '\s+', 2
    if ((Get-FileHash (Join-Path release $name) -Algorithm SHA256).Hash -ne $hash) { throw "Checksum mismatch: $name" }
}
$output = Join-Path $env:RUNNER_TEMP 'smoke-portable.json'
Invoke-CheckedProcess -File $portable.FullName -Arguments @('--smoke-test', '--output', ('"' + $output + '"'))
Test-SmokeResult $output
Invoke-CheckedProcess -File $setup.FullName -Arguments @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS', ('/DIR="' + $target + '"'))
$output = Join-Path $env:RUNNER_TEMP 'smoke-installed.json'
Invoke-CheckedProcess -File (Join-Path $target 'OmniPDF.exe') -Arguments @('--smoke-test', '--output', ('"' + $output + '"'))
Test-SmokeResult $output

# Simulate a running app; setup must wait for its exit, then restart the new EXE.
$holderScript = Join-Path $env:RUNNER_TEMP 'hold-omnipdf-mutex.py'
$ready = Join-Path $env:RUNNER_TEMP 'omnipdf-mutex-ready.txt'
@'
import ctypes, sys, time
from pathlib import Path
kernel = ctypes.WinDLL('kernel32')
kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
kernel.CreateMutexW.restype = ctypes.c_void_p
assert kernel.CreateMutexW(None, False, 'OmniPDF.App')
Path(sys.argv[1]).write_text('ready')
time.sleep(2)
'@ | Set-Content -LiteralPath $holderScript -Encoding utf8
$holder = Start-Process -FilePath (Get-Command python).Source -ArgumentList @(('"' + $holderScript + '"'), ('"' + $ready + '"')) -WindowStyle Hidden -PassThru
$deadline = [DateTime]::UtcNow.AddSeconds(10)
while (!(Test-Path -LiteralPath $ready) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 50 }
if (!(Test-Path -LiteralPath $ready)) { throw 'Update mutex helper failed to start' }
$output = Join-Path $env:RUNNER_TEMP 'smoke-updated.json'
Invoke-CheckedProcess -File $setup.FullName -Arguments @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS',
    '/OMNIPDFUPDATE=1', ('/OMNIPDFWAITPID=' + $holder.Id), ('/OMNIPDFSMOKETESTOUTPUT="' + $output + '"'), ('/DIR="' + $target + '"'))
if (!$holder.WaitForExit(5000) -or $holder.ExitCode -ne 0) { throw 'Setup did not allow the app to exit normally' }
Test-SmokeResult $output
$deadline = [DateTime]::UtcNow.AddSeconds(15)
do {
    $running = @(Get-Process OmniPDF -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq (Join-Path $target 'OmniPDF.exe') })
    if ($running.Count -eq 0) { break }
    Start-Sleep -Milliseconds 100
} while ([DateTime]::UtcNow -lt $deadline)
if ($running.Count -ne 0) { throw 'Updated smoke app did not exit' }
Invoke-CheckedProcess -File (Join-Path $target 'unins000.exe') -Arguments @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
