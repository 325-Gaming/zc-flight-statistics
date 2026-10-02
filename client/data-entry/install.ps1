# Requires Windows PowerShell 5.1. Save as UTF-8 with BOM to preserve Unicode filenames.
# Run through install.bat; -NoShortcut is intended for unattended verification.
[CmdletBinding()]
param(
    [switch]$NoShortcut,
    [ValidateScript({
        $uri = $null
        if (-not [Uri]::TryCreate($_, [UriKind]::Absolute, [ref]$uri) -or
            $uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) {
            throw 'IndexUrl must be an HTTPS package index URL without credentials, query or fragment.'
        }
        $true
    })]
    [string]$IndexUrl = 'https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$runtimeDir = Join-Path $PSScriptRoot '.runtime'
$venvDir = Join-Path $PSScriptRoot '.venv'
$pythonExe = Join-Path $venvDir 'Scripts\python.exe'
$installLock = $null
$transcribing = $false

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit $LASTEXITCODE): $Program"
    }
}

function Get-Download {
    param([string]$Url, [string]$Destination)
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination -TimeoutSec 180
}

try {
    $architecture = [Environment]::GetEnvironmentVariable('PROCESSOR_ARCHITEW6432')
    if (-not $architecture) { $architecture = $env:PROCESSOR_ARCHITECTURE }
    if ($env:OS -ne 'Windows_NT' -or $architecture -ne 'AMD64' -or
        -not [Environment]::Is64BitProcess) {
        throw 'Use 64-bit Windows 10/11 on an Intel/AMD processor and 64-bit PowerShell.'
    }
    if ([Environment]::OSVersion.Version.Major -lt 10) {
        throw 'Windows 10 or later is required.'
    }
    foreach ($required in @('main.py', 'requirements.txt', '.env.example',
        'config.example.json', 'name.example.csv', 'start.bat', 'favicon.ico')) {
        if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $required) -PathType Leaf)) {
            throw "Missing $required. Extract the entire data-entry directory first."
        }
    }
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    $installLock = [IO.File]::Open((Join-Path $runtimeDir 'install.lock'),
        [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    Start-Transcript -LiteralPath (Join-Path $runtimeDir 'install.log') -Force | Out-Null
    $transcribing = $true
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Set-Location -LiteralPath $PSScriptRoot

    # These variables affect this installer process only, never the user's PATH.
    $env:PYTHONHOME = $null
    $env:PYTHONPATH = $null
    $env:PYTHONNOUSERSITE = '1'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $runtimeDir 'python'
    $env:UV_CACHE_DIR = Join-Path $runtimeDir 'cache'
    $env:UV_PYTHON_INSTALL_BIN = '0'
    $env:UV_PYTHON_INSTALL_REGISTRY = '0'
    $env:UV_NO_MODIFY_PATH = '1'
    $env:UV_PYTHON_DOWNLOADS = 'automatic'
    # Use exactly the selected package index, even inside a configured shell.
    $env:UV_INDEX = $null
    $env:UV_EXTRA_INDEX_URL = $null
    $env:UV_INDEX_URL = $null
    $env:UV_DEFAULT_INDEX = $null

    Write-Host '[1/5] Preparing the local installation tool...'
    # Digest from the official GitHub release asset metadata. Update together.
    $uvVersion = '0.12.17'
    $uvHash = 'a252121d5b59398fcb137c6ea448176459a44010f33f67e0072305a637119ca7'
    $uvArchive = Join-Path $runtimeDir "uv-$uvVersion.zip"
    if (-not (Test-Path -LiteralPath $uvArchive) -or
        (Get-FileHash -LiteralPath $uvArchive -Algorithm SHA256).Hash -ne $uvHash) {
        $partial = "$uvArchive.part"
        Get-Download "https://github.com/astral-sh/uv/releases/download/$uvVersion/uv-x86_64-pc-windows-msvc.zip" $partial
        if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ne $uvHash) {
            throw 'uv download checksum mismatch. No downloaded program was executed.'
        }
        Move-Item -LiteralPath $partial -Destination $uvArchive -Force
    }
    $uvDir = Join-Path $runtimeDir "uv-$uvVersion"
    Expand-Archive -LiteralPath $uvArchive -DestinationPath $uvDir -Force
    $uvExe = Join-Path $uvDir 'uv.exe'
    Invoke-Checked $uvExe @('--version')

    Write-Host '[2/5] Checking the Microsoft Visual C++ runtime...'
    $systemDir = [Environment]::SystemDirectory
    $missingRuntime = @('msvcp140.dll', 'msvcp140_1.dll', 'vcruntime140.dll', 'vcruntime140_1.dll') |
        Where-Object { -not (Test-Path -LiteralPath (Join-Path $systemDir $_)) }
    if ($missingRuntime) {
        Write-Host 'Installing the Microsoft runtime. Windows may ask for administrator approval.'
        $vcInstaller = Join-Path $runtimeDir 'vc_redist.x64.exe'
        Get-Download 'https://aka.ms/vs/17/release/vc_redist.x64.exe' $vcInstaller
        $signature = Get-AuthenticodeSignature -LiteralPath $vcInstaller
        if ($signature.Status -ne 'Valid' -or
            $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation(?:,|$)') {
            throw 'Microsoft runtime signature verification failed.'
        }
        $vcProcess = Start-Process -FilePath $vcInstaller -ArgumentList '/install', '/passive', '/norestart' -Verb RunAs -Wait -PassThru
        if ($vcProcess.ExitCode -notin @(0, 1638, 3010)) {
            throw "Microsoft runtime installation failed (exit $($vcProcess.ExitCode))."
        }
        if ($vcProcess.ExitCode -eq 3010) {
            throw 'Windows requires a restart. Restart Windows, then run install.bat again.'
        }
    }

    Write-Host '[3/5] Preparing an isolated Python 3.11 environment...'
    if (Test-Path -LiteralPath $venvDir) {
        if (-not (Test-Path -LiteralPath $pythonExe)) {
            throw 'Incomplete .venv. Close the client, remove only .venv, then run install.bat again.'
        }
        $checkEnvironment = @'
import pathlib
import struct
import sys
assert sys.version_info[:2] == (3, 11), 'Expected Python 3.11; remove .venv and retry'
assert struct.calcsize('P') == 8, 'Expected 64-bit Python'
assert pathlib.Path(sys.base_prefix).is_relative_to(pathlib.Path(sys.argv[1])), 'Existing .venv is not managed here; remove .venv and retry'
print(sys.executable)
'@
        Invoke-Checked $pythonExe @('-c', $checkEnvironment, $env:UV_PYTHON_INSTALL_DIR)
    } else {
        Invoke-Checked $uvExe @('venv', '--no-config', '--managed-python', '--python', '3.11', $venvDir)
    }

    Write-Host '[4/5] Installing dependencies (ONNX Runtime)...'
    Write-Host "Package index: $IndexUrl"
    Invoke-Checked $uvExe @('pip', 'install', '--no-config', '--python', $pythonExe,
        '--default-index', $IndexUrl, '--only-binary', ':all:',
        '-r', (Join-Path $PSScriptRoot 'requirements.txt'))
    Invoke-Checked $uvExe @('pip', 'check', '--no-config', '--python', $pythonExe)
    # Do not import main.py: it contacts the service and requires a real token.
    $smokeTest = @'
import httpx
import mss
import numpy
import tkinter
from PIL import Image, ImageTk
from dotenv import load_dotenv
import onnxruntime
assert 'CPUExecutionProvider' in onnxruntime.get_available_providers()
root = tkinter.Tk()
root.withdraw()
root.destroy()
with httpx.Client(http2=True):
    pass
print('Python, dependencies and Tk GUI checks passed.')
'@
    Invoke-Checked $pythonExe @('-c', $smokeTest)

    Write-Host '[5/5] Preparing configuration and the launch shortcut...'
    foreach ($pair in @(@('.env.example', '.env'), @('config.example.json', 'config.json'), @('name.example.csv', 'name.csv'))) {
        $destination = Join-Path $PSScriptRoot $pair[1]
        if (-not (Test-Path -LiteralPath $destination)) {
            [IO.File]::Copy((Join-Path $PSScriptRoot $pair[0]), $destination, $false)
        }
    }
    if (-not $NoShortcut) {
        try {
            $desktop = [Environment]::GetFolderPath('DesktopDirectory')
            $shell = New-Object -ComObject WScript.Shell
            $shortcut = $shell.CreateShortcut((Join-Path $desktop 'Zc航空抽卡统计数据录入.lnk'))
            $shortcut.TargetPath = Join-Path $PSScriptRoot 'start.bat'
            $shortcut.WorkingDirectory = $PSScriptRoot
            $shortcut.IconLocation = (Join-Path $PSScriptRoot 'favicon.ico') + ',0'
            $shortcut.Save()
        } catch {
            Write-Warning "Could not create the desktop shortcut. Use start.bat instead. $($_.Exception.Message)"
        }
    }
    Write-Host 'Installation complete. Existing configuration and models were preserved.'
    Write-Host 'Before the first launch, edit .env and replace ZCFLIGHT_LOGIN_TOKEN=replace-me with your token.'
    Write-Host 'Then double-click start.bat or the desktop shortcut. Models download on first launch.'
    Write-Host 'Keep this directory in place. Close the client before rerunning the installer.'
} catch {
    Write-Host "Installation failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($transcribing) { Stop-Transcript | Out-Null }
    if ($null -ne $installLock) { $installLock.Dispose() }
}
