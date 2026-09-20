# Integration test: downloads and installs real dependencies in a temporary copy.
# Run with 64-bit Windows PowerShell 5.1. No business service is contacted.
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'This integration test requires Windows.' }

$testName = 'zc install ' + [char]0x6D4B + [char]0x8BD5 + ' ' + [Guid]::NewGuid().ToString('N')
$testDir = Join-Path ([IO.Path]::GetTempPath()) $testName
New-Item -ItemType Directory -Path $testDir | Out-Null
$lock = $null

try {
    # Explicitly exclude all real tokens, local configuration, models and output.
    foreach ($pattern in @('*.py', '*.bat', '*.ps1', '*.example', '*.example.json', '*.example.csv', 'requirements.txt', 'favicon.ico')) {
        Get-ChildItem -LiteralPath $PSScriptRoot -Filter $pattern -File -Force |
            Copy-Item -Destination $testDir
    }
    $installer = Join-Path $testDir 'install.ps1'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -NoShortcut
    if ($LASTEXITCODE -ne 0) { throw 'Fresh installation failed.' }

    # Use synthetic data to verify that reinstalling preserves every byte.
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    $sentinels = @{
        '.env' = "ZCFLIGHT_LOGIN_TOKEN=integration-test-only`n"
        'config.json' = '{"event_name":"keep-test-config"}'
        'name.csv' = "keep-test-passenger`n"
        'models\operators.txt' = "keep-test-model-data`n"
    }
    New-Item -ItemType Directory -Path (Join-Path $testDir 'models') | Out-Null
    foreach ($name in $sentinels.Keys) {
        [IO.File]::WriteAllText((Join-Path $testDir $name), $sentinels[$name], $utf8)
    }
    $before = @{}
    foreach ($name in $sentinels.Keys) {
        $before[$name] = (Get-FileHash -LiteralPath (Join-Path $testDir $name)).Hash
    }

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -NoShortcut
    if ($LASTEXITCODE -ne 0) { throw 'Repeated installation failed.' }
    foreach ($name in $sentinels.Keys) {
        if ((Get-FileHash -LiteralPath (Join-Path $testDir $name)).Hash -ne $before[$name]) {
            throw "Reinstallation modified $name."
        }
    }

    $lock = [IO.File]::Open((Join-Path $testDir '.runtime\install.lock'),
        [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -NoShortcut
    if ($LASTEXITCODE -eq 0) { throw 'Concurrent installer was not rejected.' }
    Write-Host 'PASS: fresh install, paths with spaces/Unicode, reinstall preservation, concurrent install rejection.'
} finally {
    if ($null -ne $lock) { $lock.Dispose() }
    # Keep logs and the environment for diagnosis; never touch the source copy.
    Write-Host "Test files retained at: $testDir"
}
