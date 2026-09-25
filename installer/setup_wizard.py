"""
KOE — Windows Web Installer Wizard
Installs KOE to %LOCALAPPDATA%\\Programs\\KOE, downloads dependencies,
configures embedded Python & FFmpeg, registers shortcuts and PATH.
"""

import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import winreg
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

# Configure theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

PYTHON_EMBED_URL = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"


class InstallerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("KOE (声) — Setup & Installation")
        self.geometry("620x640")
        self.resizable(False, False)

        # Resource folder (bundled via PyInstaller or local)
        if getattr(sys, "frozen", False):
            self.bundle_dir = Path(sys._MEIPASS)
        else:
            self.bundle_dir = Path(__file__).resolve().parent

        # Set Window Icon
        icon_path = self.bundle_dir / "assets" / "icon.ico"
        if icon_path.exists():
            try:
                self.iconbitmap(str(icon_path))
            except Exception:
                pass

        self.default_install_dir = os.path.expandvars(r"%LOCALAPPDATA%\Programs\KOE")
        self.is_installing = False
        self.log_queue = queue.Queue()

        self._build_ui()
        self._poll_logs()

    def _build_ui(self):
        self.main_container = ctk.CTkFrame(self, corner_radius=12)
        self.main_container.pack(fill="both", expand=True, padx=16, pady=16)

        # Header with Logo
        header_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        header_frame.pack(pady=(16, 12))

        icon_png = self.bundle_dir / "assets" / "icon.png"
        if icon_png.exists():
            try:
                pil_img = Image.open(icon_png)
                logo_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(56, 56))
                logo_label = ctk.CTkLabel(header_frame, image=logo_img, text="")
                logo_label.pack(side="left", padx=(0, 14))
            except Exception:
                pass

        title_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_frame.pack(side="left")

        ctk.CTkLabel(
            title_frame,
            text="KOE (声) Setup",
            font=ctk.CTkFont(size=24, weight="bold")
        ).pack(anchor="w")

        ctk.CTkLabel(
            title_frame,
            text="Subtitle Diarization & Audio Leveling Suite",
            font=ctk.CTkFont(size=12),
            text_color="gray70"
        ).pack(anchor="w")

        # Config Card
        self.config_card = ctk.CTkFrame(self.main_container, corner_radius=8)
        self.config_card.pack(fill="x", padx=16, pady=(0, 10))

        # Target Folder
        ctk.CTkLabel(
            self.config_card,
            text="Installation Folder:",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=14, pady=(10, 2))

        folder_frame = ctk.CTkFrame(self.config_card, fg_color="transparent")
        folder_frame.pack(fill="x", padx=14, pady=(0, 10))

        self.folder_entry = ctk.CTkEntry(folder_frame)
        self.folder_entry.insert(0, self.default_install_dir)
        self.folder_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        browse_btn = ctk.CTkButton(
            folder_frame,
            text="Browse...",
            width=80,
            command=self._browse_folder
        )
        browse_btn.pack(side="right")

        # Gemini API Key Entry
        ctk.CTkLabel(
            self.config_card,
            text="Gemini API Key (Optional — can be set later):",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=14, pady=(2, 2))

        self.key_entry = ctk.CTkEntry(
            self.config_card,
            placeholder_text="Enter AI Studio API key (or leave blank)",
            show="*"
        )
        self.key_entry.pack(fill="x", padx=14, pady=(0, 10))

        # Shortcuts Options
        ctk.CTkLabel(
            self.config_card,
            text="Shortcuts & Integration:",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=14, pady=(2, 2))

        options_frame = ctk.CTkFrame(self.config_card, fg_color="transparent")
        options_frame.pack(fill="x", padx=14, pady=(0, 12))

        self.desktop_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(options_frame, text="Add Shortcut to Desktop", variable=self.desktop_var).pack(anchor="w", pady=3)

        self.start_menu_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(options_frame, text="Add Shortcut to Start Menu", variable=self.start_menu_var).pack(anchor="w", pady=3)

        self.path_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(options_frame, text="Add 'koe' command to Windows Terminal PATH", variable=self.path_var).pack(anchor="w", pady=3)

        # Progress / Status Section
        self.progress_bar = ctk.CTkProgressBar(self.main_container)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=16, pady=(4, 4))

        self.status_label = ctk.CTkLabel(
            self.main_container,
            text="Ready to install. An internet connection is required.",
            font=ctk.CTkFont(size=12),
            text_color="gray70"
        )
        self.status_label.pack(pady=(0, 6))

        # Console Log
        self.log_textbox = ctk.CTkTextbox(
            self.main_container,
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word",
            height=130
        )
        self.log_textbox.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        # Action Button Frame
        action_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        action_frame.pack(fill="x", padx=16, pady=(0, 8))

        self.install_btn = ctk.CTkButton(
            action_frame,
            text="Install KOE Now",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=42,
            command=self._start_install
        )
        self.install_btn.pack(side="right", fill="x", expand=True)

    def _browse_folder(self):
        chosen = filedialog.askdirectory(title="Select Destination Folder")
        if chosen:
            self.folder_entry.delete(0, "end")
            self.folder_entry.insert(0, chosen)

    def _log(self, text: str):
        self.log_queue.put(text + "\n")

    def _poll_logs(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_textbox.configure(state="normal")
                self.log_textbox.insert("end", msg)
                self.log_textbox.see("end")
                self.log_textbox.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(50, self._poll_logs)

    def _start_install(self):
        if self.is_installing:
            return

        target_dir = Path(self.folder_entry.get().strip())
        api_key = self.key_entry.get().strip()

        self.is_installing = True
        self.install_btn.configure(state="disabled", text="Installing...")
        self.status_label.configure(text="Installing... please wait", text_color="cyan")

        threading.Thread(
            target=self._install_worker,
            args=(target_dir, api_key),
            daemon=True
        ).start()

    def _download_file(self, url: str, dest_path: Path, label: str):
        self._log(f"Downloading {label}...")
        
        def reporthook(count, block_size, total_size):
            if total_size > 0:
                percent = min(1.0, (count * block_size) / total_size)
                self.progress_bar.set(percent)
                self.status_label.configure(text=f"Downloading {label}: {int(percent * 100)}%")

        urllib.request.urlretrieve(url, str(dest_path), reporthook=reporthook)
        self._log(f"✓ Downloaded {label}")

    def _install_worker(self, target_dir: Path, api_key: str):
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            runtime_dir = target_dir / "runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)

            # Step 1: Unpack application files from embedded payload
            self.status_label.configure(text="[1/6] Unpacking application files...")
            self._log("[1/6] Unpacking application files...")
            payload_zip = self.bundle_dir / "app_payload.zip"
            if payload_zip.exists():
                with zipfile.ZipFile(payload_zip, "r") as zf:
                    zf.extractall(target_dir)
                self._log("✓ Extracted core scripts and assets")
            else:
                self._log("Warning: app_payload.zip not found, skipping payload extraction.")

            # Step 2: Download Python 3.12 embedded
            self.status_label.configure(text="[2/6] Downloading Python 3.12 runtime...")
            self._log("\n[2/6] Downloading embedded Python 3.12 runtime from python.org...")
            python_zip = target_dir / "python_embed.zip"
            self._download_file(PYTHON_EMBED_URL, python_zip, "Python 3.12 Embedded Runtime")

            self._log("Extracting Python runtime...")
            with zipfile.ZipFile(python_zip, "r") as zf:
                zf.extractall(runtime_dir)
            python_zip.unlink()

            # Step 3: Configure Python .pth file
            self.status_label.configure(text="[3/6] Configuring Python environment...")
            self._log("\n[3/6] Configuring Python path and site-packages...")
            pth_file = runtime_dir / "python312._pth"
            if pth_file.exists():
                pth_content = pth_file.read_text(encoding="utf-8")
                pth_content = pth_content.replace("#import site", "import site")
                pth_content = f"python312.zip\n.\nLib\nLib\\site-packages\n..\nimport site\n"
                pth_file.write_text(pth_content, encoding="utf-8")
                self._log("✓ Enabled site-packages support in Python embed")

            # Extract Tkinter support bundle if present in payload
            tk_zip = self.bundle_dir / "tk_bundle.zip"
            if tk_zip.exists():
                self._log("Extracting Tkinter support files...")
                with zipfile.ZipFile(tk_zip, "r") as zf:
                    zf.extractall(runtime_dir)
                self._log("✓ Installed Tkinter GUI backend into runtime")

            # Step 4: Install pip and dependencies
            self.status_label.configure(text="[4/6] Installing dependencies via pip...")
            self._log("\n[4/6] Installing pip and application packages...")
            get_pip_py = target_dir / "get-pip.py"
            self._download_file(GET_PIP_URL, get_pip_py, "pip bootstrap")

            python_exe = runtime_dir / "python.exe"
            self._log("Bootstrapping pip...")
            subprocess.run(
                [str(python_exe), str(get_pip_py), "--no-warn-script-location"],
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            get_pip_py.unlink()
            self._log("✓ pip installed successfully")

            req_file = target_dir / "requirements.txt"
            if req_file.exists():
                self._log("Installing dependencies (google-genai, customtkinter, pillow, pydantic, dotenv)...")
                self.status_label.configure(text="Installing packages from PyPI (this may take a minute)...")
                subprocess.run(
                    [str(python_exe), "-m", "pip", "install", "-r", str(req_file), "--no-warn-script-location"],
                    check=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                self._log("✓ All Python dependencies installed successfully")

            # Step 5: Check / configure FFmpeg
            self.status_label.configure(text="[5/6] Checking FFmpeg...")
            self._log("\n[5/6] Checking FFmpeg availability...")
            system_ffmpeg = shutil.which("ffmpeg")
            local_ffmpeg = runtime_dir / "ffmpeg.exe"

            if local_ffmpeg.exists():
                self._log(f"✓ Found local FFmpeg: {local_ffmpeg}")
            elif system_ffmpeg:
                self._log(f"✓ Found system FFmpeg: {system_ffmpeg}")
            else:
                self._log("System FFmpeg not found. Downloading standalone FFmpeg build...")
                # Fallback: Gyan essentials or portable build
                # We can download Gyan essentials zip and extract ffmpeg.exe
                try:
                    ffmpeg_zip = target_dir / "ffmpeg_temp.zip"
                    self._download_file(
                        "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
                        ffmpeg_zip,
                        "FFmpeg essentials"
                    )
                    with zipfile.ZipFile(ffmpeg_zip, "r") as zf:
                        for member in zf.namelist():
                            if member.endswith("bin/ffmpeg.exe"):
                                with zf.open(member) as src, open(local_ffmpeg, "wb") as dst:
                                    shutil.copyfileobj(src, dst)
                                break
                    ffmpeg_zip.unlink()
                    self._log("✓ Portable FFmpeg installed to runtime/ffmpeg.exe")
                except Exception as e:
                    self._log(f"Note: Could not download FFmpeg automatically ({e}). If audio leveling is needed, install FFmpeg on PATH.")

            # Step 6: Create .env configuration
            env_file = target_dir / ".env"
            if not env_file.exists() or api_key:
                env_content = f"GEMINI_API_KEY={api_key if api_key else 'your-api-key-here'}\nGEMINI_MODEL=gemini-3.8-flash\n"
                env_file.write_text(env_content, encoding="utf-8")
                self._log("✓ Created .env configuration")

            # Shortcuts & Registry
            self.status_label.configure(text="[6/6] Creating shortcuts and registering app...")
            self._log("\n[6/6] Creating Windows shortcuts...")

            launch_target = target_dir / "launch_gui.bat"
            icon_ico = target_dir / "assets" / "icon.ico"

            # Create Desktop Shortcut
            if self.desktop_var.get():
                ps_cmd = (
                    f"$ws = New-Object -ComObject WScript.Shell; "
                    f"$desk = [Environment]::GetFolderPath('Desktop'); "
                    f"$s = $ws.CreateShortcut($desk + '\\KOE.lnk'); "
                    f"$s.TargetPath = '{launch_target}'; "
                    f"$s.WorkingDirectory = '{target_dir}'; "
                    f"$s.IconLocation = '{icon_ico},0'; "
                    f"$s.Description = 'KOE - Speaker Diarization and Audio Leveler'; "
                    f"$s.Save()"
                )
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], creationflags=subprocess.CREATE_NO_WINDOW)
                self._log("✓ Created Desktop shortcut")

            # Create Start Menu Shortcut
            if self.start_menu_var.get():
                ps_cmd = (
                    f"$ws = New-Object -ComObject WScript.Shell; "
                    f"$start = [Environment]::GetFolderPath('Programs'); "
                    f"$s = $ws.CreateShortcut($start + '\\KOE.lnk'); "
                    f"$s.TargetPath = '{launch_target}'; "
                    f"$s.WorkingDirectory = '{target_dir}'; "
                    f"$s.IconLocation = '{icon_ico},0'; "
                    f"$s.Description = 'KOE - Speaker Diarization and Audio Leveler'; "
                    f"$s.Save()"
                )
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], creationflags=subprocess.CREATE_NO_WINDOW)
                self._log("✓ Created Start Menu shortcut")

            # Add to User PATH
            if self.path_var.get():
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_ALL_ACCESS) as key:
                        current_path, _ = winreg.QueryValueEx(key, "Path")
                        if str(target_dir) not in current_path:
                            new_path = f"{current_path};{target_dir}"
                            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
                            self._log(f"✓ Added {target_dir} to User PATH")
                except Exception as e:
                    self._log(f"Note: Could not add to PATH automatically ({e})")

            # Create Uninstaller Script
            uninstall_bat = target_dir / "uninstall.bat"
            uninstall_bat.write_text(
                f"@echo off\n"
                f"echo Uninstalling KOE...\n"
                f"if exist \"%USERPROFILE%\\Desktop\\KOE.lnk\" del \"%USERPROFILE%\\Desktop\\KOE.lnk\"\n"
                f"if exist \"%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\KOE.lnk\" del \"%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\KOE.lnk\"\n"
                f"reg delete HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\KOE /f >nul 2>&1\n"
                f"timeout /t 2 >nul\n"
                f"rmdir /s /q \"{target_dir}\"\n"
                f"echo KOE has been uninstalled.\n"
                f"pause\n",
                encoding="utf-8"
            )

            # Register in Windows Add/Remove Programs
            try:
                reg_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\KOE"
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
                    winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "KOE (声) — Subtitle Diarization & Audio Leveler")
                    winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "1.1.0")
                    winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "syamsulrahmat")
                    winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(target_dir))
                    winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(icon_ico))
                    winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'cmd.exe /c "{uninstall_bat}"')
                self._log("✓ Registered in Windows Installed Apps (Settings)")
            except Exception as e:
                self._log(f"Note: Registry uninstaller key skipped ({e})")

            self.progress_bar.set(1.0)
            self.status_label.configure(text="✓ Installation Complete!", text_color="#34D399")
            self._log("\n🎉 KOE has been successfully installed!")

            self.after(0, self._show_complete, target_dir)

        except Exception as e:
            self._log(f"\n❌ Installation failed: {e}")
            self.status_label.configure(text=f"Failed: {e}", text_color="#F87171")
            self.after(0, lambda: messagebox.showerror("Installation Error", f"Installation failed:\n{e}"))
            self.is_installing = False
            self.install_btn.configure(state="normal", text="Retry Install")

    def _show_complete(self, target_dir: Path):
        self.install_btn.configure(
            state="normal",
            text="✓ Finish & Launch KOE",
            fg_color="#10B981",
            hover_color="#059669",
            command=lambda: self._finish_and_launch(target_dir)
        )

    def _finish_and_launch(self, target_dir: Path):
        launch_bat = target_dir / "launch_gui.bat"
        if launch_bat.exists():
            subprocess.Popen([str(launch_bat)], shell=True)
        self.destroy()


def main():
    app = InstallerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
