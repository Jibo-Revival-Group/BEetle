# Synthetic tests only: never starts WSL, an MSI, DISM, or any real child process.
$ErrorActionPreference = 'Stop'
$bootstrap = Join-Path $PSScriptRoot 'bootstrap.ps1'
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($bootstrap, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
foreach ($definition in $ast.FindAll({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] }, $false)) {
    Invoke-Expression $definition.Extent.Text
}
$originalAdmin = (Get-Item Function:Invoke-ApprovedAdmin).ScriptBlock
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('beetle-offline-test-' + [guid]::NewGuid().ToString('N'))
$previousSystemRoot = $env:SystemRoot
try {
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    $env:SystemRoot = $testRoot
    $installer = Join-Path $testRoot 'wsl.msi'
    [IO.File]::WriteAllText($installer, 'fixture installer')
    $hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash
    @{ schema = 1; files = @{ 'wsl.msi' = @{ sha256 = $hash } } } |
        ConvertTo-Json -Depth 5 | Set-Content (Join-Path $testRoot 'offline-manifest.json')
    $script:signatureStatus = 'Valid'
    $script:publisher = 'CN=Microsoft Corporation'
    $script:adminCalls = @()
    function Get-AuthenticodeSignature {
        param([string]$LiteralPath)
        return [pscustomobject]@{
            Status = $script:signatureStatus
            SignerCertificate = [pscustomobject]@{ Subject = $script:publisher }
        }
    }
    function Invoke-ApprovedAdmin {
        param([string]$File, [string]$Arguments)
        $script:adminCalls += @([pscustomobject]@{ File = $File; Arguments = $Arguments })
    }
    Install-BundledMsi -Root $testRoot -Name 'wsl.msi' -Publisher 'Microsoft Corporation'
    if ($script:adminCalls.Count -ne 1 -or
        $script:adminCalls[0].File -notlike '*msiexec.exe' -or
        $script:adminCalls[0].Arguments -notlike '*/norestart*') { throw 'Bundled MSI invocation was incorrect.' }
    $script:adminCalls = @()
    foreach ($scenario in @('bad-signature', 'wrong-publisher', 'wrong-checksum')) {
        $script:signatureStatus = 'Valid'
        $script:publisher = 'CN=Microsoft Corporation'
        if ($scenario -eq 'bad-signature') { $script:signatureStatus = 'NotTrusted' }
        if ($scenario -eq 'wrong-publisher') { $script:publisher = 'CN=Other Publisher' }
        if ($scenario -eq 'wrong-checksum') { [IO.File]::WriteAllText($installer, 'tampered') }
        $blocked = $false
        try { Install-BundledMsi -Root $testRoot -Name 'wsl.msi' -Publisher 'Microsoft Corporation' }
        catch { $blocked = $true }
        if (-not $blocked -or $script:adminCalls.Count) { throw "Unsafe installer was accepted: $scenario" }
    }
    Set-Item Function:Invoke-ApprovedAdmin $originalAdmin
    $script:fakeExit = 3010
    function Start-Process {
        param($FilePath, $ArgumentList, $Verb, $WindowStyle, [switch]$Wait, [switch]$PassThru)
        return [pscustomobject]@{ ExitCode = $script:fakeExit }
    }
    Invoke-ApprovedAdmin -File 'synthetic-installer' -Arguments 'none'
    $script:fakeExit = 1603
    $blocked = $false
    try { Invoke-ApprovedAdmin -File 'synthetic-installer' -Arguments 'none' }
    catch { $blocked = $true }
    if (-not $blocked) { throw 'MSI failure was hidden.' }
    Write-Output 'PASS: bundled MSI hash, publisher, signature, reboot and failure handling; no installers run.'
} finally {
    $env:SystemRoot = $previousSystemRoot
    Remove-Item -LiteralPath $testRoot -Recurse -Force
}
