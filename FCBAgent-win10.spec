# -*- mode: python ; coding: utf-8 -*-
# ══════════════════════════════════════════════════════════════
#  FCBAgent.spec — PyInstaller spec para FCBAgent v1.0
#  Federação Columbófila Brasileira
#  Gera: FCBAgent.exe (executável único, sem console)
# ══════════════════════════════════════════════════════════════

block_cipher = None

a = Analysis(
    ['fcbagent.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Incluir certificados SSL (necessário para HTTPS no .exe)
        ('fcbagent.ico', '.'),
    ],
    hiddenimports=[
        # Tkinter
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.scrolledtext',
        # Serial
        'serial',
        'serial.tools',
        'serial.tools.list_ports',
        'serial.tools.list_ports_common',
        'serial.tools.list_ports_windows',
        # Requests + SSL
        'requests',
        'requests.adapters',
        'requests.auth',
        'urllib3',
        'urllib3.util',
        'urllib3.util.retry',
        'certifi',
        'charset_normalizer',
        'idna',
        # Pillow
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageTk',
        # Pystray
        'pystray',
        'pystray._win32',
        # Windows
        'winreg',
        'ctypes',
        'ctypes.wintypes',
        # Stdlib
        'queue',
        'threading',
        'logging',
        'json',
        'pathlib',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Excluir módulos desnecessários para reduzir tamanho
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
        'setuptools',
        'docutils',
        'email',
        'html',
        'http.server',
        'xmlrpc',
        'pydoc',
        'unittest',
        'distutils',
        'lib2to3',
        'multiprocessing',
        'asyncio',
        'concurrent',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='FCBAgent-Win10-11',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,           # Compressão UPX (reduz tamanho ~30%)
    upx_exclude=[
        'vcruntime140.dll',
        'python3*.dll',
    ],
    runtime_tmpdir=None,
    console=False,      # SEM janela de console preta
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='x86_64',
    codesign_identity=None,
    entitlements_file=None,
    icon='fcbagent.ico',
    version_info=None,
    # Manifesto UAC — executar sem privilégios de admin
    uac_admin=False,
    uac_uiaccess=False,
)
