from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project_root = Path(SPECPATH).parent
web_root = project_root / "src" / "hmanga" / "web"
locale_root = project_root / "src" / "hmanga" / "locales"

datas = []
binaries = []
hiddenimports = []
for package in (
    "uvicorn",
    "fastapi",
    "sqlalchemy",
    "pillow_heif",
    "watchdog",
    "qrcode",
    "multipart",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

if web_root.exists():
    datas.append((str(web_root), "hmanga/web"))
if locale_root.exists():
    datas.append((str(locale_root), "hmanga/locales"))

a = Analysis(
    [str(project_root / "src" / "hmanga" / "__main__.py")],
    pathex=[str(project_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HManga",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
debug_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HManga-Debug",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
coll = COLLECT(
    exe,
    debug_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="HManga",
)
