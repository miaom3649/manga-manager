$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Push-Location frontend
npm install
npm run lint
npm test -- --run
npm run build
Pop-Location

python -m pytest
python -m ruff check src tests migrations
python -m PyInstaller --noconfirm packaging/HLibrary.spec

$Smoke = Start-Process -FilePath "dist\HLibrary\HLibrary.exe" -ArgumentList "--version" -Wait -PassThru
if ($Smoke.ExitCode -ne 0) {
    throw "Packaged application smoke test failed with exit code $($Smoke.ExitCode)"
}

$Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $Iscc)) {
    throw "Inno Setup 6 not found: $Iscc"
}
& $Iscc packaging/HLibrary.iss
