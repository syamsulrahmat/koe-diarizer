"""
KOE — Speaker Diarization Assignment (Reference SRT)

Usage:
    python transcribe.py <audio_file> <reference_srt_file>

Example:
    python transcribe.py interview.wav interview_reference.srt
"""

import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from dataclasses import dataclass

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field


MAX_RETRIES = 4
RETRY_DELAYS = [10, 30, 60, 120]  # seconds

# ---------------------------------------------------------------------------
# Internal Data Structures
# ---------------------------------------------------------------------------

@dataclass
class SubtitleBlock:
    id: int
    original_id_str: str
    raw_timestamp: str  # e.g., "00:00:01,200 --> 00:00:04,500"
    raw_text: str       # Exact text, including newlines


# ---------------------------------------------------------------------------
# SRT Parsing
# ---------------------------------------------------------------------------

def parse_srt(srt_path: Path) -> list[SubtitleBlock]:
    """Parse an SRT file into a list of SubtitleBlocks."""
    content = srt_path.read_text(encoding="utf-8")
    
    # Remove BOM if present
    if content.startswith('\ufeff'):
        content = content[1:]

    # Standard SRT blocks are separated by double newline
    blocks = re.split(r'(?:\r?\n){2,}', content.strip())
    
    parsed_blocks = []
    for block in blocks:
        if not block.strip():
            continue
            
        lines = block.split('\n')
        lines = [line.rstrip('\r') for line in lines]
        
        # An SRT block must have at least ID, Timestamp, and Text
        if len(lines) >= 3:
            try:
                original_id_str = lines[0]
                sub_id = int(original_id_str.strip())
                timestamp = lines[1]
                text = "\n".join(lines[2:])
                parsed_blocks.append(SubtitleBlock(
                    id=sub_id,
                    original_id_str=original_id_str,
                    raw_timestamp=timestamp, 
                    raw_text=text
                ))
            except ValueError:
                print(f"Warning: Could not parse SRT block:\n{block}")
    
    return parsed_blocks


# ---------------------------------------------------------------------------
# Schema — defines the structured JSON that Gemini must return
# ---------------------------------------------------------------------------

class SubtitleAssignment(BaseModel):
    subtitle_id: int = Field(
        description="The original subtitle index/number from the reference list"
    )
    speaker: str = Field(
        description="Speaker label, e.g., 'Speaker 1', 'Speaker 2'. "
                    "Use consistent labels throughout."
    )
    confidence: str = Field(
        description="Confidence level of this assignment: 'high', 'medium', or 'low' (if uncertain)"
    )

class AssignmentResult(BaseModel):
    assignments: list[SubtitleAssignment] = Field(
        description="List of speaker assignments for every subtitle provided"
    )


# ---------------------------------------------------------------------------
# Gemini API Interaction
# ---------------------------------------------------------------------------

ASSIGNMENT_PROMPT_TEMPLATE = """\
You are an expert audio analyzer. You are provided with an audio recording and a reference list of subtitles. 
Your ONLY task is to identify which speaker is speaking during each subtitle.

Listen to the audio and read the provided subtitles.
Return a list of assignments mapping the subtitle_id to the speaker label (e.g., "Speaker 1", "Speaker 2").
If you are uncertain about an assignment, mark confidence as "low", but still provide your best guess.

CRITICAL RULES:
1. Do not skip any subtitle IDs. You must provide an assignment for every subtitle in the list.
2. Do not modify the text or timing. Just return the ID, speaker, and confidence.
3. Keep speaker labels consistent across the entire file.

Reference Subtitles:
{subtitles_text}
"""


def upload_audio(client: genai.Client, audio_path: Path) -> object:
    """Upload an audio file to the Gemini Files API."""
    print(f"[1/4] Uploading {audio_path.name} to Gemini Files API...")

    mime_type = mimetypes.guess_type(str(audio_path))[0] or "audio/wav"

    try:
        audio_path.name.encode("ascii")
        return client.files.upload(file=str(audio_path))
    except UnicodeEncodeError:
        pass

    safe_name = f"koe_upload{audio_path.suffix}"
    tmp_dir = tempfile.mkdtemp()
    tmp_path = Path(tmp_dir) / safe_name

    try:
        try:
            os.link(str(audio_path), str(tmp_path))
        except OSError:
            print("  (copying to temp location for upload...)")
            shutil.copy2(str(audio_path), str(tmp_path))

        audio_file = client.files.upload(
            file=str(tmp_path),
            config=types.UploadFileConfig(
                display_name=audio_path.name,
                mime_type=mime_type,
            ),
        )
    finally:
        tmp_path.unlink(missing_ok=True)
        Path(tmp_dir).rmdir()

    return audio_file


def assign_speakers(client: genai.Client, audio_file: object, subtitles: list[SubtitleBlock], model: str = "gemini-3.1-pro") -> AssignmentResult:
    """Send audio and parsed SRT to Gemini to get speaker assignments."""
    print(f"[2/4] Requesting speaker assignments from Gemini (Model: {model})...")

    # Format subtitles for the prompt
    formatted_subs = []
    for sub in subtitles:
        formatted_subs.append(f"[ID] {sub.id}\n[Time] {sub.raw_timestamp}\n[Text] {sub.raw_text}\n")
    subtitles_text = "\n".join(formatted_subs)
    
    prompt = ASSIGNMENT_PROMPT_TEMPLATE.format(subtitles_text=subtitles_text)

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[audio_file, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=AssignmentResult,
                    temperature=0.1,
                ),
            )
            break
        except Exception as e:
            error_str = str(e)
            is_retryable = any(code in error_str for code in ["503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED"])
            if is_retryable and attempt < MAX_RETRIES:
                delay = RETRY_DELAYS[attempt]
                print(f"  ⏳ Server busy (attempt {attempt + 1}/{MAX_RETRIES + 1}), retrying in {delay}s...")
                time.sleep(delay)
            else:
                raise

    result = response.parsed
    if result is None:
        result = AssignmentResult.model_validate_json(response.text)

    return result


# ---------------------------------------------------------------------------
# Audio Processing
# ---------------------------------------------------------------------------

def level_audio_master(audio_path: Path, output_dir: Path) -> Path | None:
    """
    Applies transparent dynamic dialogue normalization and true-peak limiting.
    Outputs a unified leveled master track.
    """
    print("[*] Processing unified leveled master audio...")
    out_file = output_dir / f"{audio_path.stem}_leveled.wav"
    
    # Check if FFmpeg is available
    if not shutil.which("ffmpeg"):
        print("❌ ERROR: FFmpeg is not installed or not in PATH. Cannot process audio.")
        return None

    # Filtergraph:
    # 1. highpass=f=80 (Remove rumble/mic bumps)
    # 2. dynaudnorm=p=0.9:m=10:s=5:g=15 (Dynamic normalizer targeting dialogue)
    # 3. loudnorm=I=-16:LRA=11:TP=-1.5 (Broadcast standard normalization)
    # 4. alimiter=limit=-1.5dB (True-peak brickwall)
    filtergraph = (
        "highpass=f=80,"
        "dynaudnorm=p=0.9:m=10:s=5:g=15,"
        "loudnorm=I=-16:LRA=11:TP=-1.5:print_format=summary,"
        "alimiter=limit=-1.5dB"
    )

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(audio_path),
        "-af", filtergraph,
        "-ar", "48000",
        "-c:a", "pcm_s16le",
        str(out_file)
    ]

    try:
        subprocess.run(cmd, check=True)
        print(f"✓ Leveled master audio saved to: {out_file.name}")
        return out_file
    except subprocess.CalledProcessError as e:
        print(f"❌ ERROR: FFmpeg audio processing failed: {e}")
        return None

def srt_time_to_seconds(time_str: str) -> float:
    # time_str format: "00:00:01,200"
    parts = time_str.replace(",", ":").split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0

def generate_split_stems(leveled_wav_path: Path, output_dir: Path, speaker_groups: dict) -> list[Path]:
    """
    Reads the leveled WAV file and isolates each speaker into their own dedicated track
    based on SRT boundaries, preserving pristine time sync and audio fidelity.
    """
    print("[*] Generating Split Speaker Stems...")
    
    with wave.open(str(leveled_wav_path), "rb") as wav_in:
        params = wav_in.getparams()
        n_channels = params.nchannels
        sampwidth = params.sampwidth
        framerate = params.framerate
        n_frames = params.nframes
        raw_audio = bytearray(wav_in.readframes(n_frames))
        
    bytes_per_frame = n_channels * sampwidth
    padding_sec = 0.3  # Add 300ms padding so breaths/tails aren't chopped abruptly
    
    generated_files = []
    
    for speaker_name, subs in speaker_groups.items():
        # Initialize a silent bytearray of the exact same length as the master track
        speaker_audio = bytearray(len(raw_audio))
        
        for sub in subs:
            try:
                start_str, end_str = sub.raw_timestamp.split(" --> ")
                start_sec = max(0.0, srt_time_to_seconds(start_str.strip()) - padding_sec)
                end_sec = srt_time_to_seconds(end_str.strip()) + padding_sec
                
                start_frame = int(start_sec * framerate)
                end_frame = int(end_sec * framerate)
                
                start_byte = start_frame * bytes_per_frame
                # Ensure bytes align perfectly with frame boundaries
                start_byte = start_byte - (start_byte % bytes_per_frame)
                
                end_byte = min(end_frame * bytes_per_frame, len(raw_audio))
                end_byte = end_byte - (end_byte % bytes_per_frame)
                
                if start_byte < end_byte:
                    speaker_audio[start_byte:end_byte] = raw_audio[start_byte:end_byte]
            except Exception as e:
                print(f"Warning: Failed to process audio bounds for subtitle {sub.id}: {e}")
                
        stem_name = f"{leveled_wav_path.stem.replace('_leveled', '')}_{speaker_name}.wav"
        stem_path = output_dir / stem_name
        
        with wave.open(str(stem_path), "wb") as wav_out:
            wav_out.setparams(params)
            wav_out.writeframes(speaker_audio)
            
        generated_files.append(stem_path)
        print(f"  └── {stem_name}")
        
    return generated_files


# ---------------------------------------------------------------------------
# Main Logic
# ---------------------------------------------------------------------------

def main():
    script_dir = Path(__file__).resolve().parent
    load_dotenv(script_dir / ".env")

    parser = argparse.ArgumentParser(
        description="KOE — Speaker Diarization Assignment (Reference SRT)"
    )
    parser.add_argument("audio_file", help="Path to the source audio file (wav, mp3, etc.)")
    parser.add_argument("reference_srt", nargs="?", default=None, help="Path to the reference SRT file (optional if only using -l to level audio)")
    
    # Core Options
    parser.add_argument(
        "--model", "-m",
        default=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        help="Gemini model name to use (e.g. 'gemini-3.8-flash', 'gemini-3.1-pro-preview'). Default: 'gemini-3.8-flash'."
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=None,
        help="Directory to save outputs. Default: the directory containing the reference SRT file."
    )
    
    # Audio Processing Options
    audio_group = parser.add_argument_group('Audio Processing Options')
    audio_group.add_argument(
        "--level-audio", "-l",
        action="store_true",
        help="Process and output a unified, balanced audio track (e.g., audio_leveled.wav). Can run entirely offline without an SRT file."
    )
    audio_group.add_argument(
        "--split-audio", "-s",
        action="store_true",
        help="Isolate each speaker into their own dedicated audio track (e.g., audio_speaker_1.wav). Mutes the track when the person is not talking. REQUIRES a reference SRT file."
    )

    args = parser.parse_args()
    start_time = time.time()

def run_workflow(
    audio_file: str | Path,
    reference_srt: str | Path | None = None,
    model: str = "gemini-3.8-flash",
    output_dir: str | Path | None = None,
    level_audio: bool = False,
    split_audio: bool = False,
):
    """
    Core execution engine for KOE. Callable from CLI or GUI.
    """
    script_dir = Path(__file__).resolve().parent
    load_dotenv(script_dir / ".env")
    start_time = time.time()

    audio_path = Path(audio_file).resolve()
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Handle Audio-Only Mode (Bypass SRT)
    if reference_srt is None or str(reference_srt).strip() == "":
        if split_audio:
            raise ValueError("Splitting audio stems (--split-audio) REQUIRES a reference SRT file to know who is speaking.")
        if not level_audio:
            raise ValueError("You must provide a reference SRT file for diarization, or enable Level Audio (-l).")
        
        audio_out_dir = Path(output_dir).resolve() if output_dir else audio_path.parent
        audio_out_dir.mkdir(parents=True, exist_ok=True)
        leveled = level_audio_master(audio_path, audio_out_dir)
        if not leveled:
            raise RuntimeError("Audio leveling failed.")
        
        elapsed = time.time() - start_time
        print(f"\n⏱️  Elapsed time: {elapsed:.2f}s")
        return [leveled]

    # Handle Normal Mode
    srt_path = Path(reference_srt).resolve()
    if not srt_path.exists():
        raise FileNotFoundError(f"SRT file not found: {srt_path}")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your-api-key-here":
        raise ValueError(f"Set your GEMINI_API_KEY in: {script_dir / '.env'}")

    out_dir = Path(output_dir).resolve() if output_dir else srt_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    client = genai.Client(api_key=api_key)

    # 1. Parse SRT
    subtitles = parse_srt(srt_path)
    if not subtitles:
        raise ValueError("No valid subtitles found in the reference SRT.")

    # 2. Upload and get assignments
    audio_file_obj = upload_audio(client, audio_path)
    assignment_result = assign_speakers(client, audio_file_obj, subtitles, model=model)

    # 3. Merge data and write report.json
    print(f"[3/4] Reconciling data and saving report.json...")
    
    assignment_map = {a.subtitle_id: a for a in assignment_result.assignments}
    report_data = []
    speaker_groups = {}

    for sub in subtitles:
        assignment = assignment_map.get(sub.id)
        speaker_label = assignment.speaker if assignment else "Unknown Speaker"
        confidence = assignment.confidence if assignment else "none"

        report_data.append({
            "subtitle_id": sub.id,
            "speaker": speaker_label,
            "confidence": confidence,
            "timestamp": sub.raw_timestamp,
            "text": sub.raw_text
        })
        speaker_groups.setdefault(speaker_label, []).append(sub)

    json_path = out_dir / "report.json"
    json_path.write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 4. Generate deterministic SRT files per speaker
    print("[4/4] Generating per-speaker SRT files...")
    created_files = []
    
    for speaker_key in sorted(speaker_groups.keys()):
        safe_speaker_name = re.sub(r'[^a-zA-Z0-9_]', '_', speaker_key.lower()).strip('_')
        if not safe_speaker_name:
            safe_speaker_name = "unknown"
        filename = f"{safe_speaker_name}.srt"
        filepath = out_dir / filename

        subs_for_speaker = speaker_groups[speaker_key]
        lines = []
        for sub in subs_for_speaker:
            lines.append(sub.original_id_str)
            lines.append(sub.raw_timestamp)
            lines.append(sub.raw_text)
            lines.append("")
        
        filepath.write_text("\n".join(lines), encoding="utf-8")
        created_files.append(filename)

    # 5. Strict Validation Step
    print("[5/5] Performing strict validation...")
    total_written = 0
    for file_name in created_files:
        written_subs = parse_srt(out_dir / file_name)
        total_written += len(written_subs)
        for w_sub in written_subs:
            orig = next((s for s in subtitles if s.id == w_sub.id), None)
            if not orig:
                raise RuntimeError(f"Subtitle ID {w_sub.id} generated but not in source!")
            if w_sub.raw_timestamp != orig.raw_timestamp:
                raise RuntimeError(f"Timestamp mismatch on subtitle {w_sub.id}")
            if w_sub.raw_text != orig.raw_text:
                raise RuntimeError(f"Text mismatch on subtitle {w_sub.id}")

    if total_written != len(subtitles):
        raise RuntimeError(f"Subtitle count mismatch! Original: {len(subtitles)}, Written: {total_written}")

    print(f"\n✓ Validation passed! All {len(subtitles)} subtitles matched byte-for-byte.")
    
    # 6. Audio Processing (Option A and B)
    if level_audio or split_audio:
        audio_out_dir = Path(output_dir).resolve() if output_dir else audio_path.parent
        leveled_file = level_audio_master(audio_path, audio_out_dir)
        
        if leveled_file:
            if level_audio:
                created_files.append(leveled_file.name)
            
            if split_audio:
                stem_paths = generate_split_stems(leveled_file, audio_out_dir, speaker_groups)
                for stem in stem_paths:
                    created_files.append(stem.name)
            
            if split_audio and not level_audio:
                leveled_file.unlink()

    print(f"✓ Output saved to: {out_dir}/")
    print(f"  ├── report.json")
    for i, f in enumerate(created_files):
        connector = "└──" if i == len(created_files) - 1 else "├──"
        print(f"  {connector} {f}")

    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = elapsed % 60
    time_str = f"{minutes}m {seconds:.1f}s" if minutes > 0 else f"{seconds:.2f}s"
    print(f"\n⏱️  Elapsed time: {time_str}")
    return created_files


def main():
    script_dir = Path(__file__).resolve().parent
    load_dotenv(script_dir / ".env")

    parser = argparse.ArgumentParser(
        description="KOE — Speaker Diarization Assignment (Reference SRT)"
    )
    parser.add_argument("audio_file", help="Path to the source audio file (wav, mp3, etc.)")
    parser.add_argument("reference_srt", nargs="?", default=None, help="Path to the reference SRT file (optional if only using -l to level audio)")
    
    # Core Options
    parser.add_argument(
        "--model", "-m",
        default=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        help="Gemini model name to use (e.g. 'gemini-3.8-flash', 'gemini-3.1-pro-preview'). Default: 'gemini-3.8-flash'."
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=None,
        help="Directory to save outputs. Default: the directory containing the reference SRT file."
    )
    
    # Audio Processing Options
    audio_group = parser.add_argument_group('Audio Processing Options')
    audio_group.add_argument(
        "--level-audio", "-l",
        action="store_true",
        help="[Option A] Process and output a unified, balanced audio track (e.g., audio_leveled.wav). Can run entirely offline without an SRT file."
    )
    audio_group.add_argument(
        "--split-audio", "-s",
        action="store_true",
        help="[Option B] Isolate each speaker into their own dedicated audio track (e.g., audio_speaker_1.wav). Mutes the track when the person is not talking. REQUIRES a reference SRT file."
    )

    args = parser.parse_args()

    try:
        run_workflow(
            audio_file=args.audio_file,
            reference_srt=args.reference_srt,
            model=args.model,
            output_dir=args.output_dir,
            level_audio=args.level_audio,
            split_audio=args.split_audio
        )
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
