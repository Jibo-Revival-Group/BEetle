[CmdletBinding()]
param([switch]$Gui, [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
$ErrorActionPreference = 'Stop'
$binary = Join-Path $PSScriptRoot 'release-out/BEetle-Windows-x64.exe'
if (Test-Path -LiteralPath $binary) {
    if ($Gui -or -not $Arguments) { & $binary gui } else { & $binary @Arguments }
    exit $LASTEXITCODE
}
$python = Get-Command py.exe -ErrorAction SilentlyContinue
if (-not $python) { throw 'Use the portable BEetle-Windows-x64.exe download, or install Python to build the native bundle. No WSL is needed.' }
$entry = Join-Path $PSScriptRoot 'scripts/release/windows_launcher.py'
if ($Gui -or -not $Arguments) { & $python.Source -3 $entry gui } else { & $python.Source -3 $entry @Arguments }
exit $LASTEXITCODE
