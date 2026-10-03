# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：把 epubcc 打成一个独立的单文件可执行程序。

用法::

    pip install pyinstaller
    pyinstaller epubcc.spec        # 产物在 dist/ 下

Windows 得到 ``dist/epubcc.exe``，Linux / macOS 得到 ``dist/epubcc``。
OpenCC 的词表（clib 下的 JSON 数据）会一并打包，用户无需再装 Python。
"""

from PyInstaller.utils.hooks import collect_all

# OpenCC 的配置与词表是运行时读取的包内数据，必须显式收集
datas, binaries, hiddenimports = collect_all("opencc")

# 可选依赖：装了就打进去，没装就跳过（运行时自动退化）
for mod in ("chardet", "cchardet", "argcomplete"):
    try:
        __import__(mod)
    except ImportError:
        continue
    hiddenimports.append(mod)

a = Analysis(
    ["epubcc.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc", "doctest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="epubcc",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
