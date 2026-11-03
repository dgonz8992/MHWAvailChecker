# Rebuild with: .venv-build/bin/python -m PyInstaller --noconfirm --clean 'MHW Scheduler.spec'
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('/etc/ssl/cert.pem', 'certificates'), ('logo/MHW-mark.png', 'logo')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['packaging/macos_ssl.py'],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MHW Scheduler',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch='universal2',
    codesign_identity=None,
    entitlements_file=None,
)
collection = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='MHW Scheduler',
)
app = BUNDLE(
    collection,
    name='MHW Scheduler.app',
    icon='logo/MHW Scheduler.icns',
    bundle_identifier='com.mhw.availabilitychecker',
    version='1.17.3',
    info_plist={
        'CFBundleDisplayName': 'MHW Scheduler',
        'NSHighResolutionCapable': True,
    },
)
