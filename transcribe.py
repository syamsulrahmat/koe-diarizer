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
import sys
import tempfile
import time
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
# Main Logic
# ---------------------------------------------------------------------------

def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="KOE — Speaker Diarization Assignment (Reference SRT)"
    )
    parser.add_argument("audio_file", help="Path to the source audio file (wav, mp3, etc.)")
    parser.add_argument("reference_srt", help="Path to the reference SRT file")
    parser.add_argument(
        "--model", "-m",
        default=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        help="Gemini model name to use (e.g. 'gemini-3.8-flash', 'gemini-3.6-flash', 'gemini-3.1-pro-preview'). Default: 'gemini-3.8-flash' or GEMINI_MODEL env var."
    )

    args = parser.parse_args()
    start_time = time.time()

    audio_path = Path(args.audio_file)
    srt_path = Path(args.reference_srt)

    if not audio_path.exists():
        print(f"Error: Audio file not found: {audio_path}")
        sys.exit(1)
    if not srt_path.exists():
        print(f"Error: SRT file not found: {srt_path}")
        sys.exit(1)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "your-api-key-here":
        print("Error: Set your GEMINI_API_KEY in the .env file.")
        sys.exit(1)

    output_dir = Path("output") / audio_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    client = genai.Client(api_key=api_key)

    # 1. Parse SRT
    subtitles = parse_srt(srt_path)
    if not subtitles:
        print("Error: No valid subtitles found in the reference SRT.")
        sys.exit(1)

    # 2. Upload and get assignments
    audio_file = upload_audio(client, audio_path)
    assignment_result = assign_speakers(client, audio_file, subtitles, model=args.model)

    # 3. Merge data and write report.json
    print(f"[3/4] Reconciling data and saving report.json...")
    
    # Build a lookup dictionary from Gemini's response
    assignment_map = {a.subtitle_id: a for a in assignment_result.assignments}
    
    report_data = []
    speaker_groups = {}  # { "Speaker 1": [SubtitleBlock, ...] }

    for sub in subtitles:
        assignment = assignment_map.get(sub.id)
        
        speaker_label = assignment.speaker if assignment else "Unknown Speaker"
        confidence = assignment.confidence if assignment else "none"

        # Add to JSON report data
        report_data.append({
            "subtitle_id": sub.id,
            "speaker": speaker_label,
            "confidence": confidence,
            "timestamp": sub.raw_timestamp,
            "text": sub.raw_text
        })

        # Add to speaker groups for SRT generation
        speaker_groups.setdefault(speaker_label, []).append(sub)

    json_path = output_dir / "report.json"
    json_path.write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 4. Generate deterministic SRT files per speaker
    print("[4/4] Generating per-speaker SRT files...")
    created_files = []
    
    # Sort speakers for deterministic ordering
    for speaker_key in sorted(speaker_groups.keys()):
        # Convert speaker label to a safe filename (e.g., "Speaker 1" -> "speaker_1.srt")
        safe_speaker_name = re.sub(r'[^a-zA-Z0-9_]', '_', speaker_key.lower()).strip('_')
        if not safe_speaker_name:
            safe_speaker_name = "unknown"
        filename = f"{safe_speaker_name}.srt"
        filepath = output_dir / filename

        subs_for_speaker = speaker_groups[speaker_key]
        lines = []
        
        # Preserve the EXACT original subtitle order and ID
        for sub in subs_for_speaker:
            lines.append(sub.original_id_str)
            lines.append(sub.raw_timestamp)
            lines.append(sub.raw_text)
            lines.append("")  # Blank line separator
        
        filepath.write_text("\n".join(lines), encoding="utf-8")
        created_files.append(filename)

    # 5. Strict Validation Step
    print("[5/5] Performing strict validation...")
    total_written = 0
    for file_name in created_files:
        written_subs = parse_srt(output_dir / file_name)
        total_written += len(written_subs)
        # Verify text and timestamps match memory exactly
        for w_sub in written_subs:
            orig = next((s for s in subtitles if s.id == w_sub.id), None)
            if not orig:
                print(f"❌ ERROR: Subtitle ID {w_sub.id} generated but not in source!")
                sys.exit(1)
            if w_sub.raw_timestamp != orig.raw_timestamp:
                print(f"❌ ERROR: Timestamp mismatch on subtitle {w_sub.id}")
                sys.exit(1)
            if w_sub.raw_text != orig.raw_text:
                print(f"❌ ERROR: Text mismatch on subtitle {w_sub.id}")
                sys.exit(1)

    if total_written != len(subtitles):
        print(f"❌ ERROR: Subtitle count mismatch! Original: {len(subtitles)}, Written: {total_written}")
        sys.exit(1)

    print(f"\n✓ Validation passed! All {len(subtitles)} subtitles matched byte-for-byte.")
    print(f"✓ Output saved to: {output_dir}/")
    print(f"  ├── report.json")
    for i, f in enumerate(created_files):
        connector = "└──" if i == len(created_files) - 1 else "├──"
        print(f"  {connector} {f}")

    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = elapsed % 60
    if minutes > 0:
        time_str = f"{minutes}m {seconds:.1f}s"
    else:
        time_str = f"{seconds:.2f}s"
    print(f"\n⏱️  Elapsed time: {time_str}")

if __name__ == "__main__":
    main()
