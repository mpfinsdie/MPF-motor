# -*- mode: python ; coding: utf-8 -*-

# ── 排除不需要的二進位 DLL（節省體積）────────────────────────────────────
EXCLUDE_BINARIES = {
    'opengl32sw.dll',       # 20MB 軟體 OpenGL 備援，有硬體 GPU 不需要
    'd3dcompiler_47.dll',   # DirectX shader compiler，純 Widget 不需要
    'libglesv2.dll',
    'libegl.dll',
}

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('Automation', 'Automation'),       # DAQNavi SDK
        ('config',     'config'),           # 閾值設定
        ('data/motor_test.db', 'data'),     # 只打包空的 SQLite DB
        # ⚠️  data/diagnostics/ 含執行時產生的 .npz 資料（~210MB），不打包
        # ⚠️  driver\Xnavi_OfflineSetup0.exe = 137MB，不打包進 exe
        # 請將 driver\ 資料夾放在 exe 同目錄，讓使用者手動安裝驅動
    ],
    hiddenimports=[
        'PyQt5.sip',
        'PyQt5.QtPrintSupport',
        'pyqtgraph',
        'pyqtgraph.graphicsItems',
        'numpy',
        # pandas 未被任何程式碼 import，不需要打包
        'openpyxl',
        'openpyxl.cell._writer',
        'sqlite3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # ── PyQt5 不需要的子模組 ──────────────────────────────
        'PyQt5.QtWebEngine',
        'PyQt5.QtWebEngineWidgets',
        'PyQt5.QtWebEngineCore',
        'PyQt5.QtWebChannel',
        'PyQt5.QtMultimedia',
        'PyQt5.QtMultimediaWidgets',
        'PyQt5.Qt3DCore',
        'PyQt5.Qt3DRender',
        'PyQt5.Qt3DInput',
        'PyQt5.Qt3DLogic',
        'PyQt5.Qt3DAnimation',
        'PyQt5.Qt3DExtras',
        'PyQt5.QtBluetooth',
        'PyQt5.QtNfc',
        'PyQt5.QtLocation',
        'PyQt5.QtPositioning',
        'PyQt5.QtQuick',
        'PyQt5.QtQuickWidgets',
        'PyQt5.QtQml',
        'PyQt5.QtDesigner',
        'PyQt5.QtTest',
        'PyQt5.QtXml',
        'PyQt5.QtXmlPatterns',
        'PyQt5.QtSql',
        'PyQt5.QtHelp',
        'PyQt5.QtOpenGL',
        'PyQt5.QtNetwork',
        'PyQt5.QtNetworkAuth',
        'PyQt5.QtRemoteObjects',
        'PyQt5.QtSensors',
        'PyQt5.QtSerialPort',
        'PyQt5.QtTextToSpeech',
        'PyQt5.QtSvg',
        # ── pandas 完全不需要（程式碼中無任何 import pandas）──
        'pandas',
        'pandas.tests',
        'pandas.plotting',
        'pandas.io.formats.style',
        'pandas.io.clipboard',
        'pandas._libs',
        'pandas.core',
        'pandas.io',
        'pandas.tseries',
        # ── numpy 不需要的部分 ────────────────────────────────
        'numpy.testing',
        'numpy.tests',
        'numpy.distutils',
        # ── 標準庫不需要的模組 ────────────────────────────────
        'tkinter',
        '_tkinter',
        # 以下標準庫被 PyInstaller runtime hook 或 pyqtgraph 間接使用，不可排除：
        # 'urllib', 'email', 'http', 'html', 'pydoc', 'doctest', 'difflib'
        'xmlrpc',
        'ftplib',
        'imaplib',
        'mailbox',
        'smtplib',
        'telnetlib',
        'turtle',
        'curses',
        'distutils',
        'setuptools',
        'pkg_resources',
        'pip',
        'lib2to3',
        'plistlib',
        'antigravity',
        'cgi',
        'cgitb',
        'chunk',
        'crypt',
        'imghdr',
        'nntplib',
        'ossaudiodev',
        'pipes',
        'sndhdr',
        'spwd',
        'sunau',
        'uu',
        'xdrlib',
        # ── 其他不需要的第三方套件 ────────────────────────────
        'matplotlib',
        'scipy',
        'IPython',
        'jupyter',
        'notebook',
        'PIL',
        'Pillow',
        'cv2',
        'sklearn',
        'tensorflow',
        'torch',
        'wx',
        'gi',
        'gtk',
    ],
    noarchive=False,
    optimize=0,
)

# ── 過濾掉不需要的大型二進位 DLL ─────────────────────────────────────────
a.binaries = [
    (name, path, kind)
    for name, path, kind in a.binaries
    if name.lower().split('\\')[-1] not in EXCLUDE_BINARIES
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MPF-Motor-Test',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        'vcruntime140.dll',
        'msvcp140.dll',
        'python310.dll',
        'Qt5Core.dll',
        'Qt5Gui.dll',
        'Qt5Widgets.dll',
        'Qt5Network.dll',
        '_ssl.pyd',
    ],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
