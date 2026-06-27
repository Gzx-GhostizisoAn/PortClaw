# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('data/portfolio.example.json', 'data'),
        ('data/portfolio_template.csv', 'data'),
        ('data/trade_template.csv', 'data'),
        ('config/local_config.example.json', 'config'),
        ('.env.example', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PortClaw',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['launchers/macos/PortClaw.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PortClaw',
)
app = BUNDLE(
    coll,
    name='PortClaw.app',
    icon='launchers/macos/PortClaw.icns',
    bundle_identifier='local.portclaw.app',
    info_plist={
        'CFBundleName': 'PortClaw',
        'CFBundleDisplayName': 'PortClaw',
        'LSApplicationCategoryType': 'public.app-category.finance',
        'NSHighResolutionCapable': True,
    },
)
