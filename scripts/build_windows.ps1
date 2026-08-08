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
python -m PyInstaller --noconfirm packaging/HManga.spec

$Smoke = Start-Process -FilePath "dist\HManga\HManga.exe" -ArgumentList "--version" -Wait -PassThru
if ($Smoke.ExitCode -ne 0) {
    throw "Packaged application smoke test failed with exit code $($Smoke.ExitCode)"
}
$DebugSmoke = Start-Process -FilePath "dist\HManga\HManga-Debug.exe" -ArgumentList "--version" -Wait -PassThru
if ($DebugSmoke.ExitCode -ne 0) {
    throw "Debug application smoke test failed with exit code $($DebugSmoke.ExitCode)"
}

$Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $Iscc)) {
    throw "Inno Setup 6 not found: $Iscc"
}
$LanguageFile = Join-Path $ProjectRoot "packaging\ChineseSimplified.isl"
if (-not (Test-Path $LanguageFile)) {
    Invoke-WebRequest `
        -Uri "https://raw.githubusercontent.com/jrsoftware/issrc/main/Files/Languages/ChineseSimplified.isl" `
        -OutFile $LanguageFile
}
if ((Get-Item $LanguageFile).Length -lt 10000) {
    throw "Downloaded Inno Setup language file is incomplete"
}
& $Iscc packaging/HManga.iss
