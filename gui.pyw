"""
KOE (声) — Modern GUI Application
Built with CustomTkinter for sleek, dark-mode desktop execution.
"""

import os
import queue
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import ctypes
from PIL import Image

import customtkinter as ctk
from transcribe import run_workflow

# Configure theme and appearance
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Set Windows AppUserModelID so the taskbar displays the custom icon properly
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("koe.srt.diarizer.app")
except Exception:
    pass


class TextRedirector:
    """Redirects stdout/stderr writes to a queue for thread-safe GUI updates."""
    def __init__(self, text_queue: queue.Queue):
        self.text_queue = text_queue

    def write(self, text: str):
        if text:
            self.text_queue.put(text)

    def flush(self):
        pass


class KoeApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("KOE (声) — Speaker Diarization & Audio Leveler")
        self.geometry("780x760")
        self.minsize(720, 680)

        # Set window icon if available
        self.assets_dir = Path(__file__).resolve().parent / "assets"
        icon_ico = self.assets_dir / "icon.ico"
        if icon_ico.exists():
            try:
                self.iconbitmap(str(icon_ico))
            except Exception:
                pass

        # Thread-safe log queue
        self.log_queue = queue.Queue()
        self.is_processing = False

        self._build_ui()
        self._start_log_listener()

    def _build_ui(self):
        # Main padding container
        main_container = ctk.CTkFrame(self, corner_radius=12)
        main_container.pack(fill="both", expand=True, padx=16, pady=16)

        # Header Frame with Icon and Title
        header_frame = ctk.CTkFrame(main_container, fg_color="transparent")
        header_frame.pack(pady=(12, 14))

        icon_png = self.assets_dir / "icon.png"
        if icon_png.exists():
            try:
                pil_img = Image.open(icon_png)
                logo_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(52, 52))
                logo_label = ctk.CTkLabel(header_frame, image=logo_img, text="")
                logo_label.pack(side="left", padx=(0, 14))
            except Exception:
                pass

        title_text_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_text_frame.pack(side="left")

        title_label = ctk.CTkLabel(
            title_text_frame,
            text="KOE (声)",
            font=ctk.CTkFont(size=26, weight="bold")
        )
        title_label.pack(anchor="w")

        subtitle_label = ctk.CTkLabel(
            title_text_frame,
            text="Precision SRT Diarization & Broadcast Audio Leveler",
            font=ctk.CTkFont(size=13),
            text_color="gray70"
        )
        subtitle_label.pack(anchor="w")

        # -------------------------------------------------------------
        # File Inputs Card
        # -------------------------------------------------------------
        files_card = ctk.CTkFrame(main_container, corner_radius=8)
        files_card.pack(fill="x", padx=16, pady=(0, 10))

        # Audio file row
        ctk.CTkLabel(
            files_card,
            text="Source Audio / Video (Required):",
            font=ctk.CTkFont(weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 2))

        self.audio_entry = ctk.CTkEntry(
            files_card,
            placeholder_text="Select audio or video file (.mp3, .wav, .mp4, .mov...)"
        )
        self.audio_entry.grid(row=1, column=0, sticky="ew", padx=(14, 8), pady=(0, 10))

        browse_audio_btn = ctk.CTkButton(
            files_card,
            text="Browse...",
            width=90,
            command=self._browse_audio
        )
        browse_audio_btn.grid(row=1, column=1, padx=(0, 14), pady=(0, 10))

        # Reference SRT row
        ctk.CTkLabel(
            files_card,
            text="Reference SRT File (Optional for audio-only leveling):",
            font=ctk.CTkFont(weight="bold")
        ).grid(row=2, column=0, sticky="w", padx=14, pady=(2, 2))

        self.srt_entry = ctk.CTkEntry(
            files_card,
            placeholder_text="Select reference .srt file (leave empty if only leveling audio)"
        )
        self.srt_entry.grid(row=3, column=0, sticky="ew", padx=(14, 8), pady=(0, 10))

        srt_btn_frame = ctk.CTkFrame(files_card, fg_color="transparent")
        srt_btn_frame.grid(row=3, column=1, padx=(0, 14), pady=(0, 10))

        browse_srt_btn = ctk.CTkButton(
            srt_btn_frame,
            text="Browse...",
            width=90,
            command=self._browse_srt
        )
        browse_srt_btn.pack(side="left", padx=(0, 4))

        clear_srt_btn = ctk.CTkButton(
            srt_btn_frame,
            text="✕",
            width=28,
            fg_color="gray35",
            hover_color="gray25",
            command=lambda: self.srt_entry.delete(0, "end")
        )
        clear_srt_btn.pack(side="left")

        # Custom output folder row
        ctk.CTkLabel(
            files_card,
            text="Custom Output Folder (Optional):",
            font=ctk.CTkFont(size=12)
        ).grid(row=4, column=0, sticky="w", padx=14, pady=(2, 2))

        self.output_entry = ctk.CTkEntry(
            files_card,
            placeholder_text="Defaults to input folder"
        )
        self.output_entry.grid(row=5, column=0, sticky="ew", padx=(14, 8), pady=(0, 12))

        browse_out_btn = ctk.CTkButton(
            files_card,
            text="Browse...",
            width=90,
            fg_color="gray40",
            hover_color="gray30",
            command=self._browse_output
        )
        browse_out_btn.grid(row=5, column=1, padx=(0, 14), pady=(0, 12))

        files_card.grid_columnconfigure(0, weight=1)

        # -------------------------------------------------------------
        # Options & Settings Card
        # -------------------------------------------------------------
        options_card = ctk.CTkFrame(main_container, corner_radius=8)
        options_card.pack(fill="x", padx=16, pady=(0, 10))

        ctk.CTkLabel(
            options_card,
            text="Processing Tasks & AI Model:",
            font=ctk.CTkFont(weight="bold")
        ).pack(anchor="w", padx=14, pady=(10, 6))

        checkboxes_frame = ctk.CTkFrame(options_card, fg_color="transparent")
        checkboxes_frame.pack(fill="x", padx=14, pady=(0, 8))

        self.level_audio_var = ctk.BooleanVar(value=True)
        self.level_audio_cb = ctk.CTkCheckBox(
            checkboxes_frame,
            text="Level Master Audio (Unified broadcast dialogue track)",
            variable=self.level_audio_var
        )
        self.level_audio_cb.pack(anchor="w", pady=4)

        self.denoise_var = ctk.BooleanVar(value=True)
        self.denoise_cb = ctk.CTkCheckBox(
            checkboxes_frame,
            text="Suppress Background Noise & Crowd Bleed (Spectral Denoising)",
            variable=self.denoise_var
        )
        self.denoise_cb.pack(anchor="w", pady=4)

        self.split_audio_var = ctk.BooleanVar(value=False)
        self.split_audio_cb = ctk.CTkCheckBox(
            checkboxes_frame,
            text="Split Speaker Stems (Requires SRT, isolates speaker_1.wav, speaker_2.wav)",
            variable=self.split_audio_var
        )
        self.split_audio_cb.pack(anchor="w", pady=4)

        # Model selection dropdown row
        model_row = ctk.CTkFrame(options_card, fg_color="transparent")
        model_row.pack(fill="x", padx=14, pady=(4, 12))

        ctk.CTkLabel(model_row, text="Gemini AI Model:").pack(side="left", padx=(0, 10))

        self.model_combo = ctk.CTkComboBox(
            model_row,
            values=[
                "gemini-3.8-flash (Recommended)",
                "gemini-3.6-flash",
                "gemini-3.1-pro-preview"
            ],
            width=260
        )
        self.model_combo.set("gemini-3.8-flash (Recommended)")
        self.model_combo.pack(side="left")

        # -------------------------------------------------------------
        # Action Button & Progress
        # -------------------------------------------------------------
        self.run_button = ctk.CTkButton(
            main_container,
            text="▶  START PROCESSING",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=44,
            command=self._on_start_clicked
        )
        self.run_button.pack(fill="x", padx=16, pady=(4, 8))

        self.progress_bar = ctk.CTkProgressBar(main_container, mode="indeterminate")
        # Hidden by default

        self.status_label = ctk.CTkLabel(
            main_container,
            text="Ready",
            font=ctk.CTkFont(size=12),
            text_color="gray70"
        )
        self.status_label.pack(pady=(0, 6))

        # -------------------------------------------------------------
        # Console Log Output
        # -------------------------------------------------------------
        log_header_frame = ctk.CTkFrame(main_container, fg_color="transparent")
        log_header_frame.pack(fill="x", padx=16, pady=(4, 2))

        ctk.CTkLabel(
            log_header_frame,
            text="Console Log Output:",
            font=ctk.CTkFont(size=12, weight="bold")
        ).pack(side="left")

        clear_log_btn = ctk.CTkButton(
            log_header_frame,
            text="Clear Log",
            width=70,
            height=22,
            font=ctk.CTkFont(size=11),
            fg_color="gray30",
            hover_color="gray20",
            command=self._clear_log
        )
        clear_log_btn.pack(side="right")

        self.log_textbox = ctk.CTkTextbox(
            main_container,
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word",
            corner_radius=8
        )
        self.log_textbox.pack(fill="both", expand=True, padx=16, pady=(0, 12))

    def _browse_audio(self):
        filetypes = [
            ("Audio/Video Files", "*.mp3 *.wav *.m4a *.aac *.flac *.mp4 *.mov *.mkv"),
            ("Audio Files", "*.mp3 *.wav *.m4a *.aac *.flac"),
            ("Video Files", "*.mp4 *.mov *.mkv *.avi"),
            ("All Files", "*.*")
        ]
        chosen = filedialog.askopenfilename(title="Select Source Audio or Video File", filetypes=filetypes)
        if chosen:
            self.audio_entry.delete(0, "end")
            self.audio_entry.insert(0, chosen)
            # Auto-suggest SRT if same folder contains .srt with matching stem
            path = Path(chosen)
            possible_srt = path.with_suffix(".srt")
            if possible_srt.exists() and not self.srt_entry.get().strip():
                self.srt_entry.insert(0, str(possible_srt))

    def _browse_srt(self):
        filetypes = [("SubRip Subtitle", "*.srt"), ("All Files", "*.*")]
        chosen = filedialog.askopenfilename(title="Select Reference SRT File", filetypes=filetypes)
        if chosen:
            self.srt_entry.delete(0, "end")
            self.srt_entry.insert(0, chosen)

    def _browse_output(self):
        chosen = filedialog.askdirectory(title="Select Output Directory")
        if chosen:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, chosen)

    def _clear_log(self):
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("1.0", "end")
        self.log_textbox.configure(state="disabled")

    def _start_log_listener(self):
        """Periodically checks queue for redirected print statements."""
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_textbox.configure(state="normal")
                self.log_textbox.insert("end", msg)
                self.log_textbox.see("end")
                self.log_textbox.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(80, self._start_log_listener)

    def _on_start_clicked(self):
        if self.is_processing:
            return

        audio_path = self.audio_entry.get().strip()
        srt_path = self.srt_entry.get().strip()
        output_dir = self.output_entry.get().strip()
        level_audio = self.level_audio_var.get()
        split_audio = self.split_audio_var.get()
        denoise = self.denoise_var.get()

        model_selected = self.model_combo.get().split(" ")[0].strip()

        if not audio_path:
            messagebox.showerror("Error", "Please select a source Audio or Video file.")
            return

        if not Path(audio_path).exists():
            messagebox.showerror("Error", f"Audio file does not exist:\n{audio_path}")
            return

        if srt_path and not Path(srt_path).exists():
            messagebox.showerror("Error", f"SRT file does not exist:\n{srt_path}")
            return

        if not srt_path and split_audio:
            messagebox.showerror(
                "Error",
                "Split Speaker Stems requires a reference SRT file to identify speaker boundaries."
            )
            return

        if not srt_path and not level_audio:
            messagebox.showerror(
                "Error",
                "Please provide a reference SRT file for diarization, or enable 'Level Master Audio'."
            )
            return

        # Start execution in background thread
        self.is_processing = True
        self.run_button.configure(state="disabled", text="⏳  Processing...")
        self.status_label.configure(text="Processing in progress...", text_color="cyan")
        self.progress_bar.pack(fill="x", padx=16, pady=(0, 6))
        self.progress_bar.start()

        worker = threading.Thread(
            target=self._worker_thread,
            args=(audio_path, srt_path, model_selected, output_dir, level_audio, split_audio, denoise),
            daemon=True
        )
        worker.start()

    def _worker_thread(self, audio_path, srt_path, model, output_dir, level_audio, split_audio, denoise):
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        redirector = TextRedirector(self.log_queue)
        sys.stdout = redirector
        sys.stderr = redirector

        success = False
        error_msg = ""

        try:
            run_workflow(
                audio_file=audio_path,
                reference_srt=srt_path if srt_path else None,
                model=model,
                output_dir=output_dir if output_dir else None,
                level_audio=level_audio,
                split_audio=split_audio,
                denoise=denoise
            )
            success = True
        except Exception as e:
            error_msg = str(e)
            print(f"\n❌ Error encountered: {error_msg}")
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            self.after(0, self._on_processing_complete, success, error_msg)

    def _on_processing_complete(self, success: bool, error_msg: str):
        self.is_processing = False
        self.progress_bar.stop()
        self.progress_bar.pack_forget()
        self.run_button.configure(state="normal", text="▶  START PROCESSING")

        if success:
            self.status_label.configure(text="✓ Completed successfully!", text_color="#34D399")
            messagebox.showinfo("Success", "KOE processing completed successfully!")
        else:
            self.status_label.configure(text=f"Failed: {error_msg}", text_color="#F87171")
            messagebox.showerror("Processing Failed", f"An error occurred:\n{error_msg}")


def main():
    app = KoeApp()
    app.mainloop()


if __name__ == "__main__":
    main()
