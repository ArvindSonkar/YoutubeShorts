# Shorts quality/progress upgrade — validation record

Validated locally on 18 November 2026 (IST). No models or dependencies were installed,
and no full 91-minute render was started. Existing `output/dmc5-auto-shorts` was preserved.

## Files and behavior

| File | Change |
|---|---|
| `workflows/gaming-shorts/auto_shorts.py` | Integrates timing, previews before encoding, review decisions, durable progress, checksums and resume counts. |
| `workflows/gaming-shorts/analyze.py` | Throttled scan progress, optional title-screen feature, protects multiple substantial motion regions. Feature version is now 2. |
| `workflows/gaming-shorts/select_highlights.py` | Opening optimization, sustained local-motion weighting, screen penalties, confidence/reasons and ending warnings. Preserves rolling relative scores, bounds, overlap suppression and diversity. |
| `workflows/gaming-shorts/autoframe.py` | Three-sample persistence, rejection of sudden target/area changes, HUD rectangle protection and safe/close/wide modes. |
| `workflows/gaming-shorts/dynamic_crop.py` | Progress-aware hashing/rendering/decode checks, conservative auto smoothing, binary-search camera interpolation, reused executable paths, encoder-finalization status and interruption cleanup. Single-clip commands remain supported. |
| `workflows/gaming-shorts/verify_output.py` | Measured metadata/frame/audio QA with full-decode progress. Existing checks and tolerances preserved. |
| `workflows/gaming-shorts/auto_defaults.json` | Adds opening/setup/payoff settings, framing mode, HUD regions and optional game profile. Existing 20–55s duration default remains. |
| `workflows/gaming-shorts/progress.py` | Monotonic timing, throttled percentage/rate/ETA, current/history JSON and Python memory measurement. |
| `workflows/gaming-shorts/review.py` | Local HTML report, browser draft/export controls, strict review identity/trim/overwrite validation. |
| `workflows/gaming-shorts/game_profiles.py` | Isolated optional DMC5 title-screen similarity rule; generic mode does not load its calibration. |
| `workflows/gaming-shorts/dmc5_title_calibration.json` | Reference patch and calibration/validation observations from the supplied recording. |
| `workflows/gaming-shorts/tests/test_upgrades.py` | 19 additional regressions covering timing, quality rules, review, resume, interruption and offline operation. |
| `README.md` | Verified CLI examples, new options, review instructions, timing semantics and limitations. |

## Automated checks

42 tests passed; 0 failed (23 original tests preserved, 19 additional tests). Final suite
duration was 0.682 seconds. Full log: `output/upgrade-investigation/tests.log`.

```powershell
python -B -m unittest discover -s workflows/gaming-shorts/tests -p "test_*.py"
```

Coverage includes deterministic percentage/speed/ETA calculations, throttling, unknown totals,
interrupted progress, monotonic stage and resumed-history totals, short candidate bounds,
opening improvement on a synthetic weak lead-in, camera-sweep penalty, title filtering,
flash/jump crop rejection, HUD preservation, crop smoothing, review bounds/identity/duplicates,
completed-output protection, real renderer subprocess kill/reap behavior under injected
interruption, batch recovery with retained partial artifacts, checksum skipping and offline
execution with sockets prohibited. Existing frame-count/audio-misalignment rejection tests pass.

`node --check` passed on the generated review JavaScript. No interactive browser end-to-end
test was run; local file playback/storage can vary between browsers. A real review JSON
import was exercised (see below). `git diff --check` passed. CLI help was checked against
argparse for both scripts, including single-clip `init` and `render`.

## Measured media smoke tests

### Original DMC5: first 120 seconds, analysis only

Command:

```powershell
python -B workflows\gaming-shorts\auto_shorts.py `
  --input "videos\DMC5.mp4" `
  --output-dir "output\dmc5-upgrade-opening-smoke-v2" `
  --count 1 --min-duration 6 --max-duration 12 `
  --max-seconds 120 --game-profile dmc5 --analysis-only --offline
```

Fresh run: **9.851 seconds wall time**, video analysis 4.895s, audio analysis 0.513s,
checksums 3.284s, previews 0.852s. Fourteen candidates; one selected. No videos rendered.
Python peak memory 111.60 MiB; child processes excluded.

This opening contains title/cutscene footage. The selected interval was 61.0–69.8s;
it is active cutscene footage, not evidence of combat recognition. The title filter does
not solve general cutscene classification.

An automatically constructed review fixture approved that candidate, trimmed it to
61.5–69.3s, and selected wide framing. A resumed analysis-only import completed in **4.244s**,
reused the analysis cache, regenerated previews, and saved source frame bounds 1845–2079
at 30 FPS. See `review-smoke.json`, `review-applied.json` and the manifest in that folder.

### Bounded combat excerpt: automatic selection and full-quality rendering

For validation only, a 30-second excerpt at source time 4297s was prepared with lossless
H.264 video and AAC audio. The full pipeline selected its own interval within that excerpt;
no production highlight timestamps are required. This lossless fixture is larger and decodes
differently from the compressed original, so its scan speed is not a long-recording benchmark.

Fixture creation (already exists; `-n` refuses overwrite):

```powershell
& "tools\ffmpeg\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe" `
  -hide_banner -loglevel error -nostdin -n `
  -ss 4297 -i "videos\DMC5.mp4" -t 30 `
  -map 0:v:0 -map 0:a:0 `
  -vf setpts=PTS-STARTPTS -af asetpts=PTS-STARTPTS `
  -c:v libx264 -crf 0 -preset ultrafast -threads 4 `
  -c:a aac -b:a 192k "output\upgrade-investigation\dmc5-combat-excerpt.mp4"
```

Render command:

```powershell
python -B workflows\gaming-shorts\auto_shorts.py `
  --input "output\upgrade-investigation\dmc5-combat-excerpt.mp4" `
  --output-dir "output\dmc5-upgrade-combat-smoke-v2" `
  --count 1 --min-duration 6 --max-duration 12 `
  --max-seconds 30 --game-profile dmc5 --offline
```

| Stage | Actual seconds |
|---|---:|
| Source probing | 0.115 |
| Checksums, including final source and output hashes | 0.934 |
| Video analysis | 4.386 |
| Audio analysis | 0.271 |
| Cache write | 0.024 |
| Scoring/selection | 0.003 |
| Framing | 0.037 |
| Three composition previews | 1.503 |
| Rendering | 28.473 |
| Verification, including source CFR timestamps | 7.537 |
| HTML reports | 0.010 |
| **Pipeline wall time, including other overhead** | **43.908** |

Five candidates; one selected and completed; zero failures. Output: **9.5 seconds, 285 frames,
1080×1920, 30 FPS, H.264 CRF 18/medium, stereo AAC 192 kbps**. Average/fastest/slowest render
were all 28.473s because this run produced one video. Python peak memory: **247.34 MiB**;
FFmpeg/FFprobe memory is not included.

Full decode passed. Sampled frame mean absolute errors were 3.553, 3.651 and 3.836
(existing failure threshold 15). Audio correlations were **0.999670** and **0.999776**
(existing threshold 0.85). Both source integrity hashes matched. The safe composition retained
the full gameplay view on this busy footage; it does not prove a tighter crop would be safe.

Repeating the same command with `--resume` took **1.211s**, verified the finished output
checksum and skipped video/audio scans, selection, previews and rendering. Current-run and
historical timing records remain separate; cumulative wall time is **45.119s**.

The earlier v1 smoke is retained. Preview generation was 3.249s there versus 1.503s after
sharing the three decoded frames across alternatives. This is a single local observation,
not a hardware-independent speedup claim. Encoder finalization now explicitly shows an
unknown ETA until FFmpeg finishes flushing its buffers.

Artifacts:

- `output/dmc5-upgrade-combat-smoke-v2/clips/short-01.mp4`
- `output/dmc5-upgrade-combat-smoke-v2/clips/short-01.qa.json`
- `output/dmc5-upgrade-combat-smoke-v2/index.html`
- `output/dmc5-upgrade-combat-smoke-v2/metrics.json` (fresh run and resume)
- `output/dmc5-upgrade-opening-smoke-v2/index.html` (reviewed analysis-only plan)
- `output/upgrade-investigation/dmc5-samples.jpg` (inspection samples)

## Game-specific evidence and deferred signals

| Signal | Evidence / disposition |
|---|---|
| Title/menu appearance | Calibrated at 0s; held-out title samples at 10s and 20s had normalized mean error 0.0033/0.0039, below 0.06. Six non-title samples at 40, 60, 90, 120, 230 and 4300s scored 0.192–0.360. Only this narrow title appearance is implemented. |
| S/SS/SSS ranks | No sufficiently labeled sequence across rank changes/effects; recognition deferred. |
| Player health | HUD visible in combat sample, but no validated temporal labels across characters and HUD layouts; change detection deferred. |
| Boss health | Bar visible in combat sample, but no calibrated health-change sequence; detection deferred. |
| Combat intensity | Generic residual-motion persistence and audio activity retained; no semantic combat label. |
| Encounter completion/victory | No labeled completion/victory sequence; detection deferred. |
| Other menus/loading screens | Generic inactivity/darkness penalties only; no broad semantic classifier. |

The calibration is limited to this recording's title appearance. It needs additional validation
for other languages, editions, capture layouts or brightness settings. Neither heuristic
confidence nor technical QA predicts views or guarantees a complete narrative.

## Performance and compatibility limits

- All processing remains local without recurring AI fees. No dependency/model downloads occurred.
- Windows reports Intel Iris Xe graphics. FFmpeg lists hardware encoders, but device/driver and
  visual/sync equivalence were not validated. CPU rendering remains enabled.
- No full 91-minute render or 1–3-hour throughput benchmark was run. Rendering remains CPU-heavy.
- Frames/audio are streamed; sampled features and candidates grow with duration. Memory values
  exclude subprocesses. Cached analysis is not checkpointed halfway through a scan.
- Timings start after argument/path validation and directory-lock acquisition. They exclude
  Python startup and the final timing-snapshot refresh. Stage measurements use a monotonic clock;
  starts are displayed in IST. Nested QA stages can overlap in the accumulated-stage sum.
- CTRL+C saves timing and render status and reaps the encoder. Forced process termination/power
  loss can lose timing since the last checkpoint; retained artifacts support safe recovery.
- Original flags/subcommands remain. Changed code/settings require a new run directory; pre-upgrade
  videos are preserved, but their caches cannot be resumed under the upgraded code signature.
- Review trimming changes interval bounds, not internal cuts. Contact sheets are still images;
  original-interval playback uses the local source. Browser interaction was not automated.

See README for full-recording analysis, rendering, resume and optional review commands.
