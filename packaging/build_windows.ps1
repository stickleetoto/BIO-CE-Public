# Copyright 2026 stickleetoto
# SPDX-License-Identifier: Apache-2.0

<#
.SYNOPSIS
Build the BIO CE Windows x64 GUI/MCP executables and the per-user Inno Setup installer.

.DESCRIPTION
PyInstaller runs with a minimal PATH (the build interpreter plus the Windows
system folders) so DLLs that happen to be on the developer's PATH, such as
app-local Universal CRT forwarders shipped by unrelated tools, cannot leak into
the bundle. Windows 10/11 provide the UCRT, so the bundle must not carry it.
#>
[CmdletBinding()]
param(
    # Python interpreter of the pinned build environment (defaults to the repository .venv).
    [string]$Python,
    # Scratch folder for PyInstaller work/dist output and the installer payload.
    [string]$BuildRoot,
    # Folder that receives the installer and SHA256SUMS.txt.
    [string]$DistRoot,
    # Inno Setup 6 command-line compiler (ISCC.exe); located automatically when omitted.
    [string]$InnoCompiler,
    # Reuse existing PyInstaller output in BuildRoot and only repackage.
    [switch]$PackageOnly
)

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'This script builds the Windows x64 release only.'
}
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $Python) { $Python = Join-Path $repo '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'Create the build venv and install requirements-mcp.lock.txt and requirements-build.lock.txt first.'
}
$Python = (Resolve-Path -LiteralPath $Python).Path
# Default output folders are per version (build\0.3.0-dev0, dist\0.3.0-dev0) so a new build can never
# overwrite the artifacts of an earlier release candidate.
$versionFolder = (& $Python -I -c "import sys, tomllib; sys.path.insert(0, sys.argv[2]); import build_assets; print(build_assets.display_version(tomllib.load(open(sys.argv[1], 'rb'))['project']['version']))" (Join-Path $repo 'pyproject.toml') (Join-Path $repo 'packaging')).Trim()
if (-not $BuildRoot) { $BuildRoot = Join-Path $repo "build\$versionFolder" }
if (-not $DistRoot) { $DistRoot = Join-Path $repo "dist\$versionFolder" }
$BuildRoot = [IO.Path]::GetFullPath($BuildRoot)
$DistRoot = [IO.Path]::GetFullPath($DistRoot)
foreach ($path in @($BuildRoot, $DistRoot)) {
    $leaf = Split-Path -Leaf $path
    if (-not $leaf -or $path -eq [IO.Path]::GetPathRoot($path) -or $path.TrimEnd('\') -eq $repo.TrimEnd('\')) {
        throw "Refusing to use $path as a generated output folder."
    }
}

# Locate the Inno Setup compiler and require a valid publisher signature on it.
if (-not $InnoCompiler) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
    )
    $InnoCompiler = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
}
if (-not $InnoCompiler -or -not (Test-Path -LiteralPath $InnoCompiler -PathType Leaf)) {
    throw 'Inno Setup 6 (ISCC.exe) was not found; installer generation is NOT RUN.'
}
$innoSignature = Get-AuthenticodeSignature -LiteralPath $InnoCompiler
if ($innoSignature.Status -ne 'Valid') {
    throw "ISCC.exe does not carry a valid Authenticode signature ($($innoSignature.Status))."
}

# Minimal, deterministic environment for every Python and PyInstaller step.
$basePrefix = (& $Python -I -c 'import sys; print(sys.base_prefix)').Trim()
$system = Join-Path $env:SystemRoot 'System32'
$env:PATH = @(
    (Split-Path -Parent $Python), $basePrefix, (Join-Path $basePrefix 'DLLs'),
    $system, $env:SystemRoot, (Join-Path $system 'Wbem'), (Join-Path $system 'WindowsPowerShell\v1.0')
) -join ';'
foreach ($name in @('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE')) {
    Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
}
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONHASHSEED = '0'
$env:PYTHONUTF8 = '1'
$tempRoot = Join-Path $BuildRoot 'tmp'
$null = New-Item -ItemType Directory -Force -Path $BuildRoot, $DistRoot

& $Python -m pip check
if ($LASTEXITCODE -ne 0) { throw 'The pinned Python environment has dependency conflicts.' }
$installedPyInstaller = (& $Python -c "from importlib.metadata import version; print(version('pyinstaller'))").Trim()
if ($installedPyInstaller -ne '6.22.3') { throw "Expected PyInstaller 6.22.3 in the build environment; found $installedPyInstaller." }

$projectVersion = (& $Python -I -c "import tomllib,sys; print(tomllib.load(open(sys.argv[1],'rb'))['project']['version'])" (Join-Path $repo 'pyproject.toml')).Trim()
$moduleVersion = (& $Python -I -c "import ast,sys; t=ast.parse(open(sys.argv[1],encoding='utf-8').read()); print(next(n.value.value for n in t.body if isinstance(n,ast.Assign) and n.targets[0].id=='__version__'))" (Join-Path $repo 'src\bio_ce\__init__.py')).Trim()
if ($projectVersion -ne $moduleVersion) { throw "pyproject version $projectVersion does not match bio_ce.__version__ $moduleVersion." }

$assets = Join-Path $BuildRoot 'assets'
$displayVersion = (& $Python -I (Join-Path $repo 'packaging\build_assets.py') --output $assets --version $projectVersion).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Failed to generate the icon and version resources.' }
$numericVersion = ((& $Python -I -c "import sys; sys.path.insert(0, sys.argv[1]); import build_assets; print('.'.join(map(str, build_assets.numeric_version(sys.argv[2]))))" (Join-Path $repo 'packaging') $projectVersion)).Trim()
$icon = Join-Path $assets 'bio-ce.ico'

$guiDist = Join-Path $BuildRoot 'gui-dist'
$guiWork = Join-Path $BuildRoot 'gui-work'
$mcpDist = Join-Path $BuildRoot 'mcp-dist'
$mcpWork = Join-Path $BuildRoot 'mcp-work'
if (-not $PackageOnly) {
    foreach ($path in @($guiDist, $guiWork, $mcpDist, $mcpWork, (Join-Path $BuildRoot 'specs'), $tempRoot)) {
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
    }
}
$null = New-Item -ItemType Directory -Force -Path $tempRoot
$env:TEMP = $tempRoot
$env:TMP = $tempRoot
$env:TMPDIR = $tempRoot

$common = @(
    '--noconfirm', '--clean', '--onedir', '--paths', (Join-Path $repo 'src'),
    '--collect-all', 'mcp.client', '--collect-all', 'mcp.server',
    '--collect-all', 'mcp.shared', '--collect-all', 'mcp.types',
    '--collect-all', 'mcp_types', '--collect-all', 'pydantic', '--noupx',
    '--icon', $icon, '--specpath', (Join-Path $BuildRoot 'specs')
)
if (-not $PackageOnly) {
    & $Python -m PyInstaller @common '--windowed' '--name' 'BIO-CE' '--version-file' (Join-Path $assets 'gui-version.txt') '--distpath' $guiDist '--workpath' $guiWork (Join-Path $repo 'src\bio_ce\gui_entry.py')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed to build BIO-CE.exe.' }
    & $Python -m PyInstaller @common '--console' '--name' 'BIO-CE-MCP' '--version-file' (Join-Path $assets 'mcp-version.txt') '--distpath' $mcpDist '--workpath' $mcpWork (Join-Path $repo 'src\bio_ce\mcp_entry.py')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed to build BIO-CE-MCP.exe.' }
}
$guiApp = Join-Path $guiDist 'BIO-CE'
$mcpApp = Join-Path $mcpDist 'BIO-CE-MCP'
if (-not (Test-Path -LiteralPath (Join-Path $guiApp 'BIO-CE.exe')) -or -not (Test-Path -LiteralPath (Join-Path $mcpApp 'BIO-CE-MCP.exe'))) {
    throw 'The expected GUI/MCP onedir outputs are missing; build them before packaging.'
}
$leakedCrt = Get-ChildItem -LiteralPath $guiApp, $mcpApp -Recurse -File |
    Where-Object { $_.Name -like 'api-ms-win-*.dll' -or $_.Name -ieq 'ucrtbase.dll' }
if ($leakedCrt) {
    throw "Universal CRT DLLs were bundled from the build PATH: $(($leakedCrt | Select-Object -ExpandProperty Name) -join ', ')"
}

$payloadRoot = Join-Path $BuildRoot 'payload'
if (Test-Path -LiteralPath $payloadRoot) { Remove-Item -LiteralPath $payloadRoot -Recurse -Force }
$null = New-Item -ItemType Directory -Force -Path $payloadRoot
Get-ChildItem -Force -LiteralPath $guiApp | Copy-Item -Destination $payloadRoot -Recurse -Force
$mcpRoot = Join-Path $payloadRoot 'MCP'
$null = New-Item -ItemType Directory -Force -Path $mcpRoot
Get-ChildItem -Force -LiteralPath $mcpApp | Copy-Item -Destination $mcpRoot -Recurse -Force
Copy-Item -LiteralPath (Join-Path $repo 'LICENSE') -Destination $payloadRoot -Force
Copy-Item -LiteralPath (Join-Path $repo 'docs\desktop-installation.md') -Destination $payloadRoot -Force
Copy-Item -LiteralPath (Join-Path $repo 'docs\desktop-security.md') -Destination $payloadRoot -Force
& $Python -I (Join-Path $repo 'packaging\collect_runtime_notices.py') --output (Join-Path $payloadRoot 'THIRD_PARTY_NOTICES') --version $displayVersion --installer-license (Join-Path (Split-Path -Parent $InnoCompiler) 'license.txt')
if ($LASTEXITCODE -ne 0) { throw 'Failed to collect bundled runtime license notices.' }

$setupName = "BIO-CE-Setup-v$displayVersion"
$targetExe = Join-Path $DistRoot "$setupName.exe"
if (Test-Path -LiteralPath $targetExe) { Remove-Item -LiteralPath $targetExe -Force }
& $InnoCompiler '/Q' "/DAppVersion=$displayVersion" "/DNumericVersion=$numericVersion" "/DPayloadDir=$payloadRoot" `
    "/DOutputDir=$DistRoot" "/DIconFile=$icon" "/DOutputBaseFilename=$setupName" (Join-Path $repo 'packaging\BIO-CE.iss')
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $targetExe -PathType Leaf)) {
    throw 'Inno Setup did not create the installer.'
}

# Record what went into the installer so a rebuild can be compared file by file.
$payloadFiles = Get-ChildItem -LiteralPath $payloadRoot -Recurse -File | Sort-Object FullName | ForEach-Object {
    [pscustomobject][ordered]@{
        path = $_.FullName.Substring($payloadRoot.Length + 1).Replace('\', '/')
        bytes = $_.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
    }
}
$sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $targetExe).Hash.ToLowerInvariant()
$manifest = [ordered]@{
    version = $displayVersion
    python = (& $Python -I -c 'import sys; print(sys.version.split()[0])').Trim()
    pyinstaller = $installedPyInstaller
    inno_setup_compiler_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $InnoCompiler).Hash.ToLowerInvariant()
    inno_setup_signer = $innoSignature.SignerCertificate.Subject
    installer = [ordered]@{ name = "$setupName.exe"; bytes = (Get-Item -LiteralPath $targetExe).Length; sha256 = $sha }
    installer_signature = (Get-AuthenticodeSignature -LiteralPath $targetExe).Status.ToString()
    payload_files = @($payloadFiles).Count
    payload_bytes = (@($payloadFiles) | Measure-Object -Property bytes -Sum).Sum
    files = @($payloadFiles)
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $BuildRoot 'build-manifest.json') -Encoding UTF8
Set-Content -LiteralPath (Join-Path $DistRoot 'SHA256SUMS.txt') -Encoding ASCII -Value "$sha  $setupName.exe"
Write-Output "Installer: $targetExe"
Write-Output "SHA-256:   $sha"
