# KOE (声) — Audio Speaker Diarization & SRT Sorter

**KOE** is a precision tool that performs speaker diarization on existing, authoritative reference SRT subtitle files using Google Gemini.

Instead of hallucinating or regenerating transcription text, **KOE treats the reference SRT as immutable**. It listens to the audio, identifies which speaker says each line, and deterministically splits the subtitles into clean, per-speaker SRT files (`speaker_1.srt`, `speaker_2.srt`, etc.) with **100% byte-for-byte fidelity** of text, timing, punctuation, and line breaks.

---

## Key Features

- **Authoritative Subtitle Preservation:** Zero text rewrite, zero timestamp drift, no deleted or merged captions.
- **Strict Byte-for-Byte Double-Blind Verification:** Automatically validates all output subtitles against the input source before saving.
- **Multimodal AI Speaker Attribution:** Utilizes Gemini (e.g. `gemini-3.8-flash` or `gemini-3.1-pro-preview`) via structured Pydantic schema mapping.
- **Detailed JSON Report:** Exports `report.json` with speaker assignments and confidence levels.
- **Unicode & Non-ASCII Safe:** Seamlessly handles Japanese file paths, full-width characters, and UTF-8 BOM headers.

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/<your-username>/koe-diarizer.git
   cd koe-diarizer
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure API Key:**
   Copy `.env.example` to `.env` and insert your Gemini API key:
   ```bash
   copy .env.example .env
   ```
   Edit `.env`:
   ```env
   GEMINI_API_KEY=your_actual_api_key_here
   GEMINI_MODEL=gemini-3.8-flash
   ```

---

## Usage

```bash
python transcribe.py <path_to_audio> <path_to_reference_srt> [options]
```

### Examples

```bash
# Basic run (uses default model in .env)
python transcribe.py interview.wav reference.srt

# Specify a custom model flag
python transcribe.py interview.mp3 reference.srt -m gemini-3.8-flash
```

---

## Output Structure

Results are organized in `output/<audio_basename>/`:

```
output/interview/
├── report.json         # Detailed assignment metadata with confidence
├── speaker_1.srt       # Exact captions spoken by Speaker 1
└── speaker_2.srt       # Exact captions spoken by Speaker 2
```
