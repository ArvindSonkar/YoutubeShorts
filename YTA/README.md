# YTA — local gameplay Shorts

YTA includes a local automatic highlight pipeline and a configurable single-clip editor.
It uses Python, OpenCV, NumPy, Pillow, FFmpeg and FFprobe. No AI API keys, inference tokens,
model downloads, uploads, or network requests are used by either processing command.

## One command for a recording

Run in PowerShell from this repository:

```powershell
cd "C:\Users\arso0922\Desktop\YTA"

python -B workflows/gaming-shorts/auto_shorts.py `
  --input "D:\Recordings\gta5-session.mp4" `
  --output-dir "output/gta5-session" `
  --count 15 `
  --offline
```

Replace the input path with your recording. Input can be outside this project; generated videos
and artifacts must remain under `YTA/output/`. The run directory must be new on the first run.
Backticks are PowerShell line continuations: do not put trailing spaces after them.

For the GTA MP4 currently in `videos/`:

```powershell
$gta = Get-ChildItem -LiteralPath ".\videos" -Filter "*GTA*.mp4"
if (@($gta).Count -ne 1) { throw "Select one GTA recording explicitly." }
python -B workflows/gaming-shorts/auto_shorts.py --input $gta.FullName --output-dir output/gta-session --count 15 --offline
```

The current example recording is about 7 minutes 40 seconds, not a 1–3 hour test source.

Default behavior:

1. Validate source compatibility and hash it once.
2. Sequentially analyze 320-pixel-wide video at 3 samples/second and streamed mono audio.
3. Score motion, camera movement, visual changes, sound energy and audio transients.
4. Propose 20–55 second intervals with lead-in/outro, rank them, and suppress overlapping
   or visually similar selections. Apply a preference for different parts of the recording.
5. Generate crop keyframes from persistent residual-motion regions. Preserve the full
   image when confidence is low. Use the existing renderer's smoothing and enlargement limits.
6. Render selected clips sequentially at 1080×1920, original frame rate, H.264/AAC.
7. Verify decoding, duration, frame count, sampled source composition and audio alignment.
8. Save MP4s, configurations, previews, QA results, a manifest and a local HTML report.

`--count 15` requests **up to 15** qualifying clips. It does not pad with low-quality or
overlapping footage when too few candidates qualify. A run with no candidates exits with code 2.

## Start with a bounded preview

```powershell
python -B workflows/gaming-shorts/auto_shorts.py `
  --input "D:\Recordings\gta5-session.mp4" `
  --output-dir "output/gta-preview" `
  --count 3 `
  --max-seconds 120 `
  --analysis-only `
  --offline
```

This analyzes only the first 120 seconds and generates plans and contact sheets. It does
not encode Shorts. It still hashes the whole source for identity/integrity checking.
Open `output/gta-preview/index.html` in a browser. The report is a local file, with no CDN,
web server or external resources.

To render the same plan, repeat the command with `--resume` and omit `--analysis-only`:

```powershell
python -B workflows/gaming-shorts/auto_shorts.py `
  --input "D:\Recordings\gta5-session.mp4" `
  --output-dir "output/gta-preview" `
  --count 3 `
  --max-seconds 120 `
  --resume `
  --offline
```

Omit `--max-seconds` in a **new** run directory to process the entire recording.

## Resume and recovery

Repeat an interrupted command with `--resume`. Source, analysis/render settings and code
must match the original run. Changes require a new output directory, protecting cached
plans and finished videos from silently mixing incompatible versions.

- Cached analysis is reused after successful completion of both scans.
- An interrupted analysis restarts the scan; analysis is not checkpointed mid-stream.
- Completed MP4s are skipped when their recorded checksums match.
- A render finished just before a crash is recovered only if its effective configuration
  matches, and it passes verification.
- Incomplete `.work` and `.partial.mp4` artifacts are retained in `attempts/` before retry.
- Existing finished videos are never silently replaced. If an existing video fails QA,
  the run records the error; use a new run directory to regenerate it.
- An OS file lock prevents two writers from processing the same run simultaneously.
- Source hashes are checked once at startup and once at completion; file stat signatures
  are checked between jobs. Resume hashes the source again.

Exit codes: `0` success/planned, `1` failure or partial completion, `2` no candidates,
`130` keyboard interruption. A partial batch preserves completed clips and records each error.

## Outputs

`output/` is disposable: it contains generated videos, previews, logs, reports and run caches,
never application code or required defaults. You can delete the entire folder; the next run
recreates it. Deleting it also deletes previous results and resume history, so start a fresh
run without `--resume` afterward. Source recordings stay in `videos/`; application code and
configuration stay in `workflows/`.

```text
output/gta-session/
  manifest.json          Settings, source fingerprint, per-clip status and output checksums
  features.npz           Cached timestamped audiovisual features (no raw full video)
  scores.npz             Sample timestamps and action scores
  candidates.json        All candidates, selection and score components
  index.html             Local report with contact sheets and completed video links
  clips/
    short-01.mp4         Verified finished video
    short-01.json        Reusable single-clip editor configuration
    short-01.jpg         Planned start/middle/end contact sheet
    short-01.qa.json      Sampled frame/audio verification results
    short-01.work/       Effective config, camera plan, FFmpeg command/log and metadata
  attempts/              Retained incomplete artifacts, if a retry was required
```

Clips are named by selection rank. The manifest stores original timestamps and per-clip
framing confidence/fallback statistics. Sampling previews do not prove every frame is ideal.

## Configuration

`workflows/gaming-shorts/auto_defaults.json` controls analysis, selection and batch settings.
`defaults.json` continues to control the existing visual renderer. Automatic jobs keep the
default hook disabled and disable impact pulses: action scores do not establish that an
actual impact occurred, and no event-specific text is fabricated.

Useful CLI options:

| Option | Default | Purpose |
|---|---:|---|
| `--count` | 15 | Maximum number of qualifying clips |
| `--min-duration` | 20 | Minimum selected clip length, seconds |
| `--max-duration` | 55 | Maximum selected clip length, seconds |
| `--min-score` | 0.30 | Candidate threshold; higher is more selective |
| `--analysis-fps` | 3 | Visual analysis samples/second |
| `--analysis-width` | 320 | Analysis image width, even integer |
| `--audio-stream` | 0 | Zero-based source audio-track ordinal |
| `--preset` | medium | CPU H.264 encoding preset |
| `--crf` | 18 | Quality setting; lower usually creates larger files |
| `--threads` | 4 | Encoder threads per clip |
| `--max-seconds` | entire input | Limit analysis for a bounded test |
| `--analysis-only` | off | Save plan/previews without encoding |
| `--resume` | off | Continue an existing matching run |
| `--offline` | always local | Explicit flag; all runs are offline regardless |

Use `--settings path/to/overrides.json` for additional settings such as `min_gap`,
`crop_confidence`, and `crop_min_width`. Unknown keys and invalid values are rejected.
CLI values override the settings file. Frame boundaries are snapped to the original frame grid.

## What the heuristic can and cannot do

This is an automatic **activity-based** editor. It does not reliably recognize gunfights,
explosions, crashes, missions, named characters or vehicles. It has no trained detector,
OCR, speech recognition, local language model, or semantic event classifier.

Cutscenes, credits, camera swings and music can produce false positives. A bounded test of
the current GTA recording's opening selected active cutscene footage; this is not evidence
of combat recognition. Raising the score threshold does not add semantic understanding.
The system cannot guarantee entertaining clips, a complete narrative, or 10–20 good moments
in every recording. Inspect the local report before publishing.

Automatic framing follows persistent motion regions, not object identity. It intentionally
falls back to full-width gameplay with a blurred background when uncertain. At 720p, a
full-height portrait crop would require substantial enlargement; exporting 1080×1920 does
not restore missing source detail. Text and HUD elements can still be lost in confident
crops; lower confidence thresholds are more aggressive and should be reviewed carefully.

Supported input: local MP4, SDR BT.709 (or unspecified color metadata), constant frame rate,
square pixels, video timeline starting at zero, no rotation, at least one audio stream.
Unsupported HDR/VFR/rotated inputs produce errors; automatic normalization/tone mapping is
not implemented. Long-session runtime and quality depend on hardware, codec and content.
CPU composition/encoding is used; GPU acceleration is not configured.

Analysis keeps sampled features in memory (proportional to duration × analysis rate), but
only a few decoded frames/audio blocks at once. It does not load the complete video into
RAM. Decoding inter-frame codecs may still require processing source reference frames even
when analysis samples are sparse. There is no published 1–3 hour benchmark yet.

## Existing single-clip editor

These commands remain available:

```powershell
python -B workflows/gaming-shorts/dynamic_crop.py doctor
python -B workflows/gaming-shorts/dynamic_crop.py --help
python -B workflows/gaming-shorts/dynamic_crop.py init --help
python -B workflows/gaming-shorts/dynamic_crop.py inspect --help
python -B workflows/gaming-shorts/dynamic_crop.py preview --help
python -B workflows/gaming-shorts/dynamic_crop.py check --help
python -B workflows/gaming-shorts/dynamic_crop.py render --help
```

Automatic per-clip JSON files can be used with `check`, `inspect` and `preview`. To manually
render a modified job, change its `output` to a fresh MP4 name under `output/` first. `render`
does not overwrite existing outputs. Do not modify jobs inside a run you intend to resume.

The scripts under `workflows/legacy/` are preserved historical Wuthering Waves examples. They are not generic
GTA entry points. The `.agents/skills` folders contain assistant workflows and text/transcript
helpers, and are not invoked by the automatic video-processing command.

## Environment and tests

The existing environment has Python 3.10.6, OpenCV-headless 4.13.0.92 (cv2 4.13.0), NumPy
2.1.1, Pillow 10.4.0 and portable FFmpeg/FFprobe 9.0.2. No install is needed here.
`workflows/gaming-shorts/requirements.txt` records the Python package versions for later
environment reproduction. Portable FFmpeg is separately retained under `tools/ffmpeg`.

Run the deterministic tests:

```powershell
python -B workflows/gaming-shorts/tests/test_pipeline.py
```

Tests cover static/loud false positives, dark footage, candidate boundaries, overlap and
duplicate removal, crop fallback/cut resets, fractional timestamps, source changes, cache
identity, output containment, and preservation of incomplete artifacts. They use temporary
files under `output/`, remove their own test files, and do not perform long-video processing.
