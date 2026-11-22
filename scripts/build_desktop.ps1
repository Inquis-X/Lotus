param([string]$OutputDirectory, [string]$PythonPath, [switch]$SkipInstall)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
$originalPath = $env:PATH
try {
    $python = if ($PythonPath) { $PythonPath } elseif (Test-Path ".venv/Scripts/python.exe") { ".venv/Scripts/python.exe" } else { "python" }
    if (-not $SkipInstall) {
        & $python -m pip install -r requirements-desktop.txt
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
    }
    if (-not $OutputDirectory) {
        $OutputDirectory = Join-Path $root ("dist/Lotus-" + (Get-Date -Format yyyyMMdd-HHmmss))
    }
    if ((Test-Path -LiteralPath $OutputDirectory) -or (Test-Path -LiteralPath "$OutputDirectory.zip")) {
        throw "Choose a new output directory: $OutputDirectory"
    }
    $release = (New-Item -ItemType Directory -Path $OutputDirectory).FullName
    $work = Join-Path $root ("build/" + [guid]::NewGuid().ToString("N"))
    & $python scripts/generate_function_demo.py --output "$release/data/gold/functions"
    if ($LASTEXITCODE -ne 0) { throw "Demo generation failed" }
    Copy-Item -LiteralPath "docs/START_WINDOWS.txt" -Destination $release
    # Resolve native dependencies against Python and Windows, without picking
    # up unrelated ICU, OpenSSL or CRT binaries from developer tools on PATH.
    $python = (Get-Command $python).Source
    $encodedBase = & $python -c "import sys, base64; print(base64.b64encode(sys.base_prefix.encode()).decode())"
    $base = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encodedBase))
    $env:PATH = (Split-Path -Parent $python), $base, "$base/DLLs", "$env:SystemRoot/System32", $env:SystemRoot -join ";"
    & $python -m PyInstaller --distpath $release --workpath $work lotus.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
    Compress-Archive -LiteralPath $release -DestinationPath "$release.zip"
    & $python scripts/check_windows_release.py "$release.zip"
    if ($LASTEXITCODE -ne 0) { throw "Packaged startup check failed" }
    Write-Host "Windows distribution: $release.zip"
} finally {
    $env:PATH = $originalPath
    Pop-Location
}
