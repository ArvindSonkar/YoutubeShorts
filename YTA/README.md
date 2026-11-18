# YTA — local gameplay Shorts

YTA includes a local automatic highlight pipeline and a configurable single-clip editor.
It uses Python, OpenCV, NumPy, Pillow, FFmpeg and FFprobe. No AI API keys, inference tokens,
model downloads, uploads, or network requests are used by either processing command.

## One command for a recording

Run in PowerShell from this repository:

```powershell
cd "C:\Users\arso0922\Desktop\Avi_Git_Repo\YoutubeShorts\YTA"

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
4. Propose 20–55 second intervals (configurable down to 2 seconds), score their openings,
   sustained activity and boundaries, and suppress overlapping
   or visually similar selections. Apply a preference for different parts of the recording.
5. Generate crop keyframes from stable residual-motion regions, including other substantial
   moving regions and configured HUD protection. Preserve the full image when confidence is low.
   Generate safe, close and wide contact sheets before encoding any video.
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
  metrics.json           Current invocation and historical stage timings, counts and cache hits
  review-applied.json    Optional imported approval/rejection/trim decisions
  clips/
    short-01.mp4         Verified finished video
    short-01.json        Reusable single-clip editor configuration
    short-01.jpg         Planned start/middle/end contact sheet
    short-01-close.jpg   Close alternative (falls back when tracking is uncertain)
    short-01-wide.jpg    Full-image alternative
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
OCR, speech recognition, local language model, or semantic event classifier. An optional
`--game-profile dmc5` adds only a calibrated title-screen similarity filter for the supplied
DMC5 Special Edition recording. It does not identify style ranks, health, victory or combat events.

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

## Quality, progress and local review upgrade

All original CLI flags remain supported. `--offline` remains explicit documentation of
always-local execution. No package or model installation is performed. Start a new output
directory after upgrading: old runs deliberately cannot resume with changed code/settings.
Their videos and reports remain intact.

For a bounded preview of the original recording (the opening includes title/cutscene footage):

```powershell
python -B workflows\gaming-shorts\auto_shorts.py `
  --input "videos\DMC5.mp4" `
  --output-dir "output\dmc5-quality-preview" `
  --count 3 `
  --min-duration 12 `
  --max-duration 40 `
  --max-seconds 120 `
  --game-profile dmc5 `
  --analysis-only `
  --offline
```

For the complete recording, automatically select and render up to 15 clips:

```powershell
python -B workflows\gaming-shorts\auto_shorts.py `
  --input "videos\DMC5.mp4" `
  --output-dir "output\dmc5-quality-full" `
  --count 15 `
  --min-duration 12 `
  --max-duration 40 `
  --game-profile dmc5 `
  --offline
```

To analyze the entire recording before rendering, add `--analysis-only` to that full command.
To resume that plan or an interrupted full render, use the same settings and directory:

```powershell
python -B workflows\gaming-shorts\auto_shorts.py `
  --input "videos\DMC5.mp4" `
  --output-dir "output\dmc5-quality-full" `
  --count 15 `
  --min-duration 12 `
  --max-duration 40 `
  --game-profile dmc5 `
  --resume `
  --offline
```

Keep `--max-seconds 120` when resuming a bounded preview. Removing that bound changes the
run signature and requires a new directory. Run commands from the YTA project directory;
relative input/output paths are resolved against the project root. Backticks must be the
last character on their lines. Existing directories are rejected without `--resume`.

New options:

| Option | Default | Behavior |
|---|---|---|
| `--game-profile generic\|dmc5` | `generic` | DMC5 mode rejects a calibrated title-screen appearance only. Other games use generic features. |
| `--framing-mode safe\|close\|wide` | `safe` | Safe uses at least 70% source width when confident; close uses `crop_min_width`; wide preserves the whole image. All modes respect protection/upscale constraints. |
| `--review-file path` | none | Imports local JSON decisions bound to this exact run. Existing completed videos cannot be edited or replaced. |

Additional `--settings` JSON keys are `opening_seconds` (1–2, default 2), `setup_seconds`
(0–5, default 1), `payoff_seconds` (0–5, default 1.5), and `hud_regions` (default `[]`).
HUD rectangles use `[left, top, right, bottom]` normalized to 0–1. For example,
`{"hud_regions": [[0.02, 0.02, 0.40, 0.15]]}` protects a top-left HUD region. Regions must
be chosen for the recording; the pipeline does not identify HUD semantics. Broad protection
can make close and wide previews identical. Full-width fallback is intentional when uncertain.

Open the run's `index.html` for scores, reasons, boundary warnings, original-interval playback,
and close/wide contact sheets. Optional review:

1. Run with `--analysis-only`.
2. Choose Automatic/Approve/Reject, framing, and source-time trim bounds in the HTML page.
3. Click **Export review JSON** and save the downloaded file locally.
4. Resume with the same command, omit `--analysis-only`, and add
   `--review-file "C:\path\to\review.json"`.

Browser drafts use local storage when supported; exported JSON is the durable, portable
record. Python saves accepted decisions as `review-applied.json`. Trims must remain within
the original candidate, last at least two seconds, and snap to the source frame grid.
Previews refresh on resume. Missing decisions remain automatic; review is never required.
This is an interval trim, not an internal jump-cut editor. The report is a local HTML file,
not a cloud service. Browsers may vary in support for local video fragment playback/storage.

Progress uses a monotonic clock, with throttled updates approximately every two seconds.
Stages print their start time (IST), elapsed time, measured work/rate, percentage where known,
and an ETA only after enough work/time has elapsed. Unknown operations show `Calculating...`.
Encoding finalization is indeterminate because submitted frames can still be buffered.
Completion/failure/interruption prints the actual stage duration. Render ETA excludes later QA.

`metrics.json` stores each invocation separately: wall time, stage samples/totals, counts,
average/fastest/slowest completed render, generated duration, cache hits and Python peak memory.
The final HTML report embeds the same measurement snapshot. Cumulative wall time sums invocations,
excluding time between them. Nested verification stages may overlap, so accumulated stage
duration is not wall time. Python memory excludes FFmpeg/FFprobe child processes. Uncatchable
process termination/power loss can leave the last saved timing checkpoint incomplete.

Performance changes reuse the same three decoded preview frames across framing alternatives,
reuse source metadata/tool paths across jobs, and use binary search for camera keyframe lookup.
Only one clip's full frame plan and a few raw preview frames are needed at a time. Sampled
features/candidate metadata still grow with recording duration; this is not constant-memory
analysis. Source hashing remains once at startup and once at successful completion; per-job
checks use file metadata. Resume safely reuses features/plans/previews and checksum-matched MP4s.

On the inspected machine, Windows reports Intel Iris Xe graphics and portable FFmpeg lists QSV,
NVENC and AMF encoders. Encoder availability is not hardware/driver/quality validation. CPU
H.264 remains the default; no GPU mode has been enabled. No 91-minute render or 1–3-hour
benchmark was performed. See [UPGRADE_VALIDATION.md](UPGRADE_VALIDATION.md) for measured tests.

## Cinematic presentation

New automatic runs default to a conservative cinematic panel with a neutral theme. Existing
single-clip JSON files without `visual` keep the original renderer. To use the original
automatic layout explicitly, pass `--visual-style original`. Original composition is tested
for pixel equality with the previous compositor; selection and audio handling are unchanged.

Generate up to ten DMC5 Shorts (this full-recording command is provided, not run as part of
the visual upgrade):

```powershell
python -B workflows\gaming-shorts\auto_shorts.py `
  --input "videos\DMC5.mp4" `
  --output-dir "output\dmc5-cinematic-10" `
  --count 10 `
  --theme dmc5 `
  --visual-style cinematic `
  --title-style cinematic `
  --subtitle "CINEMATIC GAMEPLAY" `
  --offline
```

Add `--analysis-only` to prepare previews and optional review first. Resume with the exact
same source/settings/output directory and `--resume`, omitting `--analysis-only` to render.
Use a fresh directory after this code upgrade; existing videos remain intact and old run
signatures intentionally cannot resume with changed code.

| New option | Behavior |
|---|---|
| `--visual-style original\|cinematic` | Chooses composition. Automatic default: cinematic; legacy single-clip default: original. |
| `--theme generic\|dmc5\|gta5\|gta6\|custom` | Neutral, violet, green, or pink accent, plus a default title for the named games. Independent of `--game-profile` detection. |
| `--game-title "..."` | User-provided title, at most 120 characters; overrides the theme title. Generic/custom with no supplied title has no title overlay. |
| `--title-style minimal\|cinematic\|bold` | Responsive typography preset; defaults to cinematic. Separate from `--visual-style`. |
| `--subtitle "..."` | Optional secondary title, at most 90 characters; empty by default. |
| `--context-text "..."` | User-provided context, at most 90 characters. No event descriptions are inferred. Empty by default. |
| `--creator-name "..."` | Supplies a channel name and enables branding. |
| `--creator-logo "path\logo.png"` | Supplies a local logo and enables branding. No assets are downloaded. |
| `--branding` / `--no-branding` | Explicitly enables/disables supplied branding. No name/logo is invented. |
| `--progress-line` / `--no-progress-line` | Playback progress line; disabled by default. |
| `--blur-intensity 9` | Cinematic Gaussian blur sigma, 0–30, applied at 135×240 working resolution. |
| `--glow-intensity 0.14` | Cinematic panel glow opacity, 0–0.5. |

All effects are configurable under `visual` through `--settings`. See the working example
[`cinematic-example.json`](workflows/gaming-shorts/cinematic-example.json):

```powershell
python -B workflows\gaming-shorts\auto_shorts.py `
  --input "videos\DMC5.mp4" `
  --output-dir "output\dmc5-cinematic-preview" `
  --settings "workflows\gaming-shorts\cinematic-example.json" `
  --count 2 --max-seconds 120 --analysis-only --offline
```

Theme selection supplies the accent and known game title only. Background/panel settings
remain explicit and shared, and custom `visual.accent: [R,G,B]` overrides the theme color.
The centered title uses local Segoe UI Bold, tracked lettering, a soft shadow and a thin
accent underline. `visual.title` configures its local `font`, `font_size`, `min_font_size`,
`max_lines`, `subtitle_size`, `letter_spacing`, `shadow_opacity`, `shadow_blur`, `underline`
and `uppercase`. Sizes scale from 1080px output width. `visual.fade_in` controls the existing
short overlay fade; set it to `0` to disable it. No font or asset downloads are required.
Change `visual.background.brightness`, `saturation`, `gradient` and `stabilization` independently.
These changes affect the decorative background only; the selected gameplay's colors are retained.
The background uses the same source frame without frame blending or lag. Global luminance
compression attenuates exposure flashes, but it does not eliminate local/source flashing or
make photosensitivity guarantees. It does not brighten a genuinely black source frame.

Panel padding, margin, radius and border are measured in pixels at 1080px output width and
scale with resolution. The **outer frame** has rounded corners; the full selected gameplay
rectangle sits inside it so HUD pixels are not masked. Necessary inset can exceed configured
padding when a large corner radius/border would otherwise cut the gameplay corners. Glow,
shadow and gradients operate on the small background; text/logo layers are prepared once per
job and blended only in their small regions. No per-pixel Python loops or new dependencies.

Safe-zone defaults reserve left 5.5%, right 16%, top 8%, and bottom 20% of the canvas for
decorative text/progress. These are conservative configurable design estimates, **not official
fixed YouTube coordinates**. UI placement varies by device/app. Decorations also stay out of
the entire gameplay band, so they cannot cover any source HUD. Existing `hud_regions` still
protect HUD rectangles during crop selection; safe zones do not reposition the actual YouTube
controls or guarantee that those controls never cover gameplay.

The layout uses space available across the whole clip, avoiding text jumps as framing changes.
Titles are centered on the canvas within symmetric bounds that also respect the larger
right-side safe margin. Names wrap at words (long unbroken names can split), up to three lines,
and shrink to a readable minimum when needed. The upper gameplay edge determines title space.
If a crop fills at least 80% of the canvas height at any point, optional overlays and panel
decoration are disabled for that clip. Subtitles yield to the primary title when necessary;
optional context is removed if the primary title cannot fit beside it. The title is omitted
if it still cannot fit at its minimum size. Branding and progress are omitted when they do not fit.
Long text is fitted within bounded font sizes or omitted, never placed over gameplay.
New panel defaults reduce margin/padding to 12/8px at 1080px; rounded-corner safety can increase
the actual inset. The full selected crop remains visible. Saved explicit panel settings still apply.

Reports now show original, cinematic, safe, close and wide alternatives plus the selected
composition. Review controls can select style/theme/title style and edit title, subtitle and context.
Export JSON and import with `--review-file` as before. Changes regenerate previews and remain
for subsequent resumes. Completed videos are locked. Font/logo checksums participate in
cinematic run identity, including the separate title font; changing supplied assets requires a new run.
No cloud service is used.

Render metrics now include Python CPU seconds/one-core-equivalent utilization, finished FFmpeg
CPU seconds on Windows when measurable, output bytes, and Python peak memory. FFmpeg memory
is not included in the Python memory figure. One-core utilization can exceed 100% for multiple
threads. See [CINEMATIC_VALIDATION.md](CINEMATIC_VALIDATION.md) for matched before/after results,
preview locations and limitations. See [TITLE_UPGRADE_VALIDATION.md](TITLE_UPGRADE_VALIDATION.md)
for the subsequent title upgrade's six-second comparison, tests and measured rendering cost.
No commit or push is performed automatically.

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
python -B -m unittest discover -s workflows/gaming-shorts/tests -p "test_*.py"
```

Tests cover static/loud false positives, dark footage, candidate boundaries, overlap and
duplicate removal, crop fallback/cut resets, fractional timestamps, source changes, cache
identity, output containment, and preservation of incomplete artifacts. They use temporary
files under `output/`, remove their own test files, and do not perform long-video processing.
