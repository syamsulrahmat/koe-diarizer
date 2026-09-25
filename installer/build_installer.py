"""
Builder script that compiles KOE-Setup.exe using PyInstaller.
"""

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# Ensure UTF-8 output on Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
INSTALLER_DIR = Path(__file__).resolve().parent


def build():
    print("=" * 60)
    print("       Building KOE-Setup.exe Web Installer")
    print("=" * 60)

    # 1. Create app_payload.zip
    print("\n[1/4] Packaging core application files into app_payload.zip...")
    payload_zip = INSTALLER_DIR / "app_payload.zip"
    if payload_zip.exists():
        payload_zip.unlink()

    app_files = [
        "gui.pyw",
        "transcribe.py",
        "koe.cmd",
        "launch_gui.bat",
        "requirements.txt",
        "README.md",
        ".env.example",
    ]

    with zipfile.ZipFile(payload_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in app_files:
            file_path = ROOT_DIR / f
            if file_path.exists():
                zf.write(file_path, arcname=f)
                print(f"  + {f}")

        # Add assets
        assets_dir = ROOT_DIR / "assets"
        if assets_dir.exists():
            for item in assets_dir.rglob("*"):
                if item.is_file():
                    arc_name = str(item.relative_to(ROOT_DIR))
                    zf.write(item, arcname=arc_name)
                    print(f"  + {arc_name}")

    print(f"✓ Created app_payload.zip ({payload_zip.stat().st_size / 1024:.1f} KB)")

    # 2. Package Tkinter support bundle
    print("\n[2/4] Packaging Tkinter GUI support bundle...")
    tk_zip = INSTALLER_DIR / "tk_bundle.zip"
    if tk_zip.exists():
        tk_zip.unlink()

    runtime_dir = ROOT_DIR / "runtime"
    with zipfile.ZipFile(tk_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add DLLs
        for dll in ["tcl86t.dll", "tk86t.dll", "zlib1.dll", "_tkinter.pyd"]:
            p = runtime_dir / dll
            if p.exists():
                zf.write(p, arcname=dll)
                print(f"  + {dll}")

        # Add tcl directory
        tcl_dir = runtime_dir / "tcl"
        if tcl_dir.exists():
            for item in tcl_dir.rglob("*"):
                if item.is_file():
                    arc = str(item.relative_to(runtime_dir))
                    zf.write(item, arcname=arc)
            print("  + tcl/")

        # Add Lib/tkinter directory
        tk_lib = runtime_dir / "Lib" / "tkinter"
        if tk_lib.exists():
            for item in tk_lib.rglob("*"):
                if item.is_file():
                    arc = str(item.relative_to(runtime_dir))
                    zf.write(item, arcname=arc)
            print("  + Lib/tkinter/")

    print(f"✓ Created tk_bundle.zip ({tk_zip.stat().st_size / (1024 * 1024):.1f} MB)")

    # 3. Copy assets into installer folder for PyInstaller bundling
    installer_assets = INSTALLER_DIR / "assets"
    if installer_assets.exists():
        shutil.rmtree(installer_assets)
    shutil.copytree(ROOT_DIR / "assets", installer_assets)

    # 4. Run PyInstaller to build single executable KOE-Setup.exe
    print("\n[3/4] Compiling KOE-Setup.exe with PyInstaller...")
    icon_path = ROOT_DIR / "assets" / "icon.ico"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name=KOE-Setup",
        f"--icon={icon_path}",
        f"--add-data={payload_zip};.",
        f"--add-data={tk_zip};.",
        f"--add-data={installer_assets};assets",
        str(INSTALLER_DIR / "setup_wizard.py")
    ]

    subprocess.run(cmd, cwd=str(ROOT_DIR), check=True)

    # Clean up intermediate build artifacts
    print("\n[4/4] Cleaning up temporary build artifacts...")
    if payload_zip.exists():
        payload_zip.unlink()
    if tk_zip.exists():
        tk_zip.unlink()
    if installer_assets.exists():
        shutil.rmtree(installer_assets)

    output_exe = ROOT_DIR / "dist" / "KOE-Setup.exe"
    if output_exe.exists():
        size_mb = output_exe.stat().st_size / (1024 * 1024)
        print("\n" + "=" * 60)
        print(f"🎉 SUCCESS! Installer generated:")
        print(f"   Path: {output_exe}")
        print(f"   Size: {size_mb:.2f} MB")
        print("=" * 60)


if __name__ == "__main__":
    build()
