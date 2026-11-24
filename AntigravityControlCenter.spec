# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('app_icon.ico', '.'), ('static', 'static')],
    hiddenimports=['PyQt5.QtWebEngineWidgets', 'PyQt5.QtWebEngineCore', 'PyQt5.QtWidgets', 'PyQt5.QtCore', 'PyQt5.QtGui'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'scipy', 'torch', 'cv2',
        'PIL', 'pytest', 'unittest', 'IPython', 'pandas',
        'numpy.testing'
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AntigravityControlCenter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app_icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AntigravityControlCenter',
)
