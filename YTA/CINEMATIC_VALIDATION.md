# Cinematic presentation upgrade — implementation and validation

Measured locally on 18 November 2026, IST. No full 91-minute processing was performed for
this upgrade. No dependencies/models were installed. No commit or push was made.

## Files changed

| File | Implemented change |
|---|---|
| `workflows/gaming-shorts/visuals.py` | New deterministic compositor: synchronized blur, background luminance compression/saturation/gradients, rounded outer frame, shadow/glow, adaptive safe layout, cached text/logo layers and optional progress. |
| `workflows/gaming-shorts/defaults.json` | Adds nested visual defaults; original presentation remains the default for legacy single-clip jobs. |
| `workflows/gaming-shorts/auto_defaults.json` | Conservative cinematic presentation for new automatic runs; empty context/branding, progress disabled. |
| `workflows/gaming-shorts/auto_shorts.py` | New visual CLI settings, local asset fingerprints, six shared-frame preview alternatives and per-clip review integration. |
| `workflows/gaming-shorts/dynamic_crop.py` | Reuses the existing crop/encode path, prepares cinematic layers once, saves layout metadata, records encoder CPU/size and retains original composition. |
| `workflows/gaming-shorts/verify_output.py` | Uses the identical prepared presentation for sampled frame QA; adds layout evidence to the QA result. Existing codec/frame/audio checks remain. |
| `workflows/gaming-shorts/progress.py` | Adds Python CPU measurement and optional Windows encoder CPU measurement to render metrics. |
| `workflows/gaming-shorts/review.py` | Adds original/cinematic/safe previews, style/theme selectors and user-supplied context editing. |
| `workflows/gaming-shorts/cinematic-example.json` | Configurable, ready-to-use theme/background/panel/safe-zone example. No invented creator branding. |
| `workflows/gaming-shorts/tests/test_visuals.py` | Sixteen new visual/configuration/review regressions. |
| `README.md` | Exact supported commands, defaults, units, review flow and limitations. |

Highlight scoring, interval selection, crop tracking and audio trim/encode settings were not
changed. The old `compose` path remains available with `--visual-style original`. A regression
test compares it pixel-for-pixel against a config with no visual extension.

## Visual behavior

- The moving background comes from the exact current gameplay frame. Blur, saturation,
  brightness and gradients operate at 135×240 before upsampling. Stateless exposure compression
  attenuates global brightness jumps without temporal lag or history-dependent QA.
- The selected gameplay crop is fitted intact inside a rounded outer panel. The game itself
  is not rounded/masked: an inset keeps all four gameplay corners and their HUD pixels visible.
  A thin border, low-opacity stable glow and shadow separate the panel from its background.
- Badge/context/branding placement uses the common free space across every frame in the clip.
  It does not move labels between frames. Optional elements are omitted when they do not fit.
  A clip reaching 80% canvas-height coverage uses compact styling without optional decoration.
- Theme controls accent and default title: neutral generic, violet DMC5, green GTA 5. Shared
  panel/background parameters remain independently configurable. Actual gameplay colors are
  unchanged by the visual layer.
- Context is empty unless supplied by CLI/settings/review. No event descriptions are generated.
  Branding requires a supplied name or local image. Progress is disabled by default; it was
  explicitly enabled for the demonstration. Badge/context/branding can fade in once.
- Defaults reserve top 8%, bottom 20%, right 16%, left 5.5% for decorative safe placement.
  These are configurable design estimates, not official device-independent YouTube rectangles.
  Decorations stay outside the whole gameplay band; existing source HUD protection remains.

## Tests and checks

**58 automated tests passed, 0 failed**: all 42 prior tests plus 16 new visual tests.
The final suite took 1.419s. Log: `output/cinematic-tests.log`.

```powershell
python -B -m unittest discover -s workflows/gaming-shorts/tests -p "test_*.py"
```

New coverage: original-style pixel equality, 1080×1920 gameplay-edge/corner preservation,
unchanged sharp foreground colors, no invented text/branding, safe-zone and overlap checks,
compact/mixed-crop stability, themes/custom accent, global-flash attenuation, deterministic
random-access composition, progress endpoints, safe rounding inset, invalid settings,
local logo fingerprint enforcement, bounded mask cache, review choices and HTML escaping.
Existing source/frame/audio checks, interruption kill/reap, partial-artifact preservation,
offline execution and cache/resume tests remain passing.

Generated review JavaScript passed `node --check`. Real local review JSON import changed the
preview-only plan to cinematic/DMC5 with the factual test context `DMC5 gameplay`, persisted
it in the manifest, and regenerated previews in 3.010s. No specific gameplay event or creator
identity was invented. Browser interaction itself was not automated.

## Matched original/cinematic render benchmark

Input: the existing 30-second local DMC5 combat fixture in
`output/upgrade-investigation/dmc5-combat-excerpt.mp4`, originally extracted from 4297s of
the full recording. Both runs automatically chose **the same source frames 207–387**:
180 frames, 6 seconds at 30 FPS. Identical H.264 CRF 18/medium, 4 encoder threads,
1080×1920, stereo AAC 192 kbps. Each run used a new Python process and output directory.

The original run used `--visual-style original`; the cinematic run used
`--visual-style cinematic --theme dmc5 --progress-line`. Neither supplied context or branding.
The original style ignores cinematic decorations, including the progress toggle.

| Measurement | Original | Cinematic |
|---|---:|---:|
| Render wall time, including encoder finalization | 19.306s | 22.066s |
| Effective render throughput | 9.324 frames/s | 8.158 frames/s |
| Complete pipeline wall time | 37.470s | 40.769s |
| Python CPU during rendering | 25.922 CPU-s | 25.672 CPU-s |
| Python average utilization, one-core equivalent | 134.27% | 116.34% |
| FFmpeg encoder CPU, Windows process accounting | 49.516 CPU-s | 57.344 CPU-s |
| Python process lifetime peak memory | 247.13 MiB | 249.16 MiB |
| Output size | 8,287,184 bytes | 8,360,760 bytes |
| Full decode and frame/audio QA | Passed | Passed |

The cinematic render was **14.3% slower** and its output was **0.9% larger** in this single
matched trial. No speedup is claimed. These are short CPU-bound measurements, not a 91-minute
forecast. CPU seconds sum execution across threads; one-core utilization can exceed 100%.
The machine reports 8 logical CPUs. Python memory excludes FFmpeg/FFprobe children and is a
process-lifetime high water mark, including verification; it is not whole-machine usage.

The user's existing `output/dmc5-top10/metrics.json` records approximately 1348.93s wall time
and 964.48s rendering for its earlier long run. That is a different workload and was not used
as a direct performance comparison. Its outputs were preserved.

Cinematic verification:

- 1080×1920, H.264/yuv420p, 30 FPS, 180 frames, 6.000 seconds; stereo AAC.
- Sampled frame errors: 3.824, 3.921, 4.073, below the existing mean-error threshold of 15.
- Beginning/end audio correlations: 0.999652 and 0.999690, identical to the original-style
  result and above the existing 0.85 threshold.
- An additional sequential decode of both videos read all 180 frames. No near-black frame
  met the test definition: more than 99% of grayscale pixels below 16/255.
- Source hashes matched at startup/completion. Rendered layout metadata places the badge
  within [60,154,907,1536], and the progress line outside the gameplay band.
- Same-code cinematic resume took **1.201s**, skipped cached scans/plans/previews and verified
  the completed MP4 checksum instead of rerendering it.

Machine-readable evidence:

- `output/cinematic-comparison.json`
- `output/cinematic-frame-scan.json`
- `output/dmc5-visual-original-v1/metrics.json`
- `output/dmc5-visual-cinematic-v1/metrics.json`
- Each run's `clips/short-01.qa.json` and `clips/short-01.work/` artifacts.

## Preview/video locations

- **Comparison video:** `output/cinematic-before-after.mp4` (left original, right cinematic).
  This comparison montage is 1080×960; the two actual Shorts remain 1080×1920.
- **Labeled comparison image:** `output/cinematic-before-after.png`.
- **Original Short:** `output/dmc5-visual-original-v1/clips/short-01.mp4`.
- **Cinematic Short:** `output/dmc5-visual-cinematic-v1/clips/short-01.mp4`.
- **Cinematic report:** `output/dmc5-visual-cinematic-v1/index.html`.
- **Editable review-only example:** `output/dmc5-cinematic-preview-v1/index.html`.
- Each clip has planned, original, cinematic, safe, close and wide JPG contact sheets.
  Full-size middle-frame PNGs were also extracted from the finished benchmark videos.

The comparison montage is a separately encoded presentation artifact and is not part of the
timing/quality benchmark. Its audio is copied from the original-style output; both sides
have the same source audio timing.

## Exact command for up to ten DMC5 Shorts

Run from the YTA project directory. Use a new output directory. This command has not been
executed on the full recording as part of this upgrade.

```powershell
python -B workflows\gaming-shorts\auto_shorts.py `
  --input "videos\DMC5.mp4" `
  --output-dir "output\dmc5-cinematic-10" `
  --count 10 `
  --theme dmc5 `
  --visual-style cinematic `
  --offline
```

Optional `--progress-line` enables the line shown in the demo. `--analysis-only` produces
previews first. Resume with identical settings plus `--resume`, omitting `--analysis-only`
when ready to render. `--game-profile dmc5` remains a separate optional title-screen detector;
selecting a visual theme does not change highlight selection. The requested count is a ceiling.

Example settings: `workflows/gaming-shorts/cinematic-example.json`. The example leaves context
and branding empty. Provide a real channel name/logo only when wanted. Customize `visual.accent`,
background intensity, panel dimensions, safe zones, branding opacity and progress position there.
CLI values override settings. Existing single-clip tools accept the same nested `visual` object
in their job JSON; their CLI subcommands were not expanded.

## Limits

- UI controls vary by device/app. Safe margins protect our decorations; they do not control
  YouTube's overlays or guarantee platform controls never obscure gameplay.
- Global luminance normalization attenuates background flashes, not every local flash. It is
  not a photosensitivity guarantee. Source gameplay is intentionally unmodified.
- Cinematic panel inset makes the selected gameplay slightly smaller. It never adds cropping
  or masks gameplay corners; the existing crop planner can still crop according to its settings.
- No OCR, object/event recognition, generated hooks, new music or narration was added.
- Font/logo assets must be available locally. Missing/changed assets cause explicit errors.
- Visual changes alter code/settings identity: pre-upgrade run caches require a fresh output
  directory. Existing completed videos are never overwritten. Same-version resume is tested.
- No full-recording render, GPU encoding benchmark, or measured viewer/retention improvement.
- Browser export/storage behavior was syntax-checked and JSON import tested, but a graphical
  browser end-to-end session was not run.

## Suggested Conventional Commit

```text
feat(gaming-shorts): add adaptive cinematic overlays and visual themes

- add deterministic synchronized backgrounds with configurable blur, luminance,
  saturation and gradients using the existing low-resolution composition path
- preserve complete selected gameplay inside rounded panels with cached glow
  and shadow masks, configurable accents and conservative adaptive safe zones
- support local game badges, supplied context and creator branding, plus an
  optional playback progress line; keep legacy original presentation available
- extend shared-frame previews and local review with visual style/theme choices
  and context edits, and bind supplied visual assets to automatic resume identity
- record Python/encoder CPU usage and output size alongside existing timings
- add 16 visual regressions; pass all 58 tests and matched six-second DMC5
  render, audio/frame QA, sequential frame scan and completed-run resume checks
```
