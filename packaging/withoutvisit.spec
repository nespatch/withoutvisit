# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec. Paths are relative to this file's directory.
import os

root = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))
icon = os.path.join(root, "packaging", "icon.ico")

a = Analysis(
    [os.path.join(root, "main.py")],
    pathex=[root, os.path.join(root, "app")],
    binaries=[],
    datas=[
        (os.path.join(root, "actions", "telegram_bot", "action.py"), "actions/telegram_bot"),
        (icon, "."),
    ],
    hiddenimports=[
        "pystray",
        "pystray._win32",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "pyperclip",
        "certifi",
        "clip_app",
        "clip_bar",
        "config",
        "updater",
        "selection_watcher",
        "source_detect",
        "telemetry",
        "tray",
        "core",
        "core.actions",
        "core.input",
        # action.py is loaded from disk, so its imports are not traced.
        "secrets",
        "json",
        "urllib",
        "urllib.request",
        "urllib.error",
        "webbrowser",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy"],
    noarchive=False,
    optimize=0,
)

# Pillow's hook pulls numpy and optional codecs. The app only draws a tray
# icon and reads clipboard BMP/PNG/JPEG/ICO, so drop the rest.
_DROP = ("numpy", "libscipy_openblas", "_avif", "_imagingft", "_imagingcms", "_webp", "_imagingtk")


def _keep(item):
    name = item[0].replace("\\", "/").lower()
    return not any(part in name for part in _DROP)


a.binaries = [item for item in a.binaries if _keep(item)]
a.datas = [item for item in a.datas if _keep(item)]
a.pure = [item for item in a.pure if _keep(item)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="withoutvisit",
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
    icon=icon,
    version=os.path.join(root, "packaging", "version_info.txt"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="withoutvisit",
)
