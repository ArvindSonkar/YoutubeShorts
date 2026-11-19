# Universal gaming Shorts engine — implementation and validation

Implemented and validated locally on 18–19 November 2026. The existing pipeline was extended,
not replaced. No new dependencies/models were installed, no network inference was added,
no full recording was processed, and no commit or push was made.

## What changed

- Universal ranking now uses sudden activity changes, contrast against surrounding footage,
  quieter evolving detail, static-screen penalties and existing motion/audio/cut/opening scores.
  It does not infer game-specific events or treat every loud/moving moment as interesting.
- Activity-envelope boundaries retain detected onset context and search nearby low-activity/
  audio edges. Default source duration is 15–40 seconds, with 15/25-second soft context targets.
  Existing min/max overrides remain authoritative. Dialogue/payoff understanding is not claimed.
- Action, funny and cinematic editing presets share the existing renderer. Auto reports its
  reason/confidence and falls back to neutral when evidence is ambiguous. Funny is manual only.
  Presets preserve continuous source action; no automatic internal jump cuts were added.
- GTA6 styling adds a violet glow alongside the existing pink theme, with lower default glow,
  white titles and natural gameplay colors. Themes remain independent of selection.
- Manual hooks, safe top/bottom title placement and explicitly timed reaction captions use
  the existing typography/layout system. Text that cannot fit is omitted and reported.
- Protected rectangles apply between keyframes and during punch-ins. Automatic camera plans
  anticipate future widening demands while retaining wide fallback and safe/close/wide modes.
- Explicit punch-ins, slow motion and immediate replays are supported. They default off.
  Slow motion requires pitch-preserving audio stretch or explicit mute. Rendering, previews,
  frame verification and audio verification share the edited timeline.
- Audio QA now streams native-rate samples for possible clipping, silence, boundary energy
  and explicit join discontinuities. It checks A/V timing and expected audio at bounded windows.
  Original audio is unchanged by default; no automatic music, normalization or fades.
- Diversity preferences now consider activity pattern as well as time, only among comparable
  quality candidates. Overlap and fingerprint deduplication remain enforced.
- The existing HTML/JSON review workflow includes component scores, preset suggestions,
  hook/effect/HUD overrides, durations and audio warnings. Completed outputs remain locked.
- Version-1 local candidate export and validated optional score import provide a future
  reranker/hook-provider interface. No model runs or uploads occur.

## Files changed

All code paths below are under `workflows/gaming-shorts/` unless stated otherwise.

| File | Responsibility |
|---|---|
| `moments.py` (new) | Local contrast/onset/quiet evidence, generic boundary refinement and preset suggestions. |
| `editing.py` (new) | Preset application, effect/HUD validation, frame mapping and matching audio filter graph. |
| `audio_quality.py` (new) | Streaming sample-peak, silence, clip-edge and edit-join diagnostics. |
| `candidate_exchange.py` (new) | Stable candidate IDs, bounded local frame export and validated external score blending. |
| `select_highlights.py` | New scoring evidence, boundary integration, explanatory metadata and quality-weighted diversity. |
| `auto_shorts.py` | New CLI, preset/HUD/effect integration, review/rerank handling, signatures and edited-duration accounting. |
| `dynamic_crop.py` | Persistent protection, anticipatory widening, explicit punch-ins and source/output timeline rendering. |
| `visuals.py` | GTA6 dual accents, manual hooks, title bands and timed reaction captions. |
| `verify_output.py` | Edited frame/audio references, stream timing, streaming audio diagnostics and silence failures. |
| `review.py` | Extended controls, validation, score/preset evidence and QA visibility in the same report. |
| `auto_defaults.json`, `defaults.json`, `cinematic-example.json` | Clear defaults, empty effects, optional hooks/reactions and compatible renderer settings. |
| `tests/test_universal.py` (new) | 27 additional deterministic regressions. |
| `tests/test_upgrades.py` | Extends the offline dependency check to the new modules. |
| `hud-safe-example.json` (new) | Illustrative normalized protected rectangle; not calibrated game coordinates. |
| `CANDIDATE_EXCHANGE.md` (new) | Versioned metadata/score/hook-provider contract. |
| Repository `README.md` and this report | Usage, effects/review timing, measured results and limitations. |

`analyze.py` and `autoframe.py` were inspected and reused. New evidence derives from their
existing cached signals; there is no redundant long-video analysis pass or duplicate tracker.
`title_layout.py`, existing progress metrics, source validation and output protections remain
the shared implementations.

## Exact CLI additions

```text
--editing-preset {auto,action,funny,cinematic}
--hook-text TEXT
--title-placement {auto,top,bottom}
--hud-safe-config PATH
--highlight-diversity FLOAT                 # 0..1, default 0.5
--moment-aware-boundaries
--no-moment-aware-boundaries                # refinement enabled by default
--export-candidates
--rerank-file PATH
```

Existing `--theme gta6`, `--title-style`, subtitle, framing, settings, review, resume and offline
flags remain supported. `--preset` continues to configure encoding, not editing. Detailed
effects use settings/review JSON rather than numerous timing CLI arguments. No game profile
is needed for GTA6. Plain filenames do not trigger theme selection.

Generic command, ready for a future local recording (not run here):

```powershell
python -B workflows\gaming-shorts\auto_shorts.py `
  --input "videos\GTA6.mp4" `
  --output-dir "output\gta6-top10" `
  --count 10 --offline
```

GTA6-themed bounded preview (not run here because no GTA6 recording is present):

```powershell
python -B workflows\gaming-shorts\auto_shorts.py `
  --input "videos\GTA6.mp4" `
  --output-dir "output\gta6-review" `
  --count 2 --theme gta6 --editing-preset auto `
  --max-seconds 60 --analysis-only --offline
```

After optional review, use the same source/settings/bound/output directory and import the
exported decisions. Omitting analysis-only renders just the planned candidates:

```powershell
python -B workflows\gaming-shorts\auto_shorts.py `
  --input "videos\GTA6.mp4" `
  --output-dir "output\gta6-review" `
  --count 2 --theme gta6 --editing-preset auto `
  --max-seconds 60 --resume --review-file "output\gta6-review\review.json" --offline
```

Add `--hud-safe-config "workflows\gaming-shorts\hud-safe-example.json"` only after adapting
that example to actual footage; include the same setting on every resume. Add `--export-candidates`
to an analysis-only run for local candidate frames/metadata. Import scores before manual
review/rendering using `--resume --analysis-only --rerank-file path/to/scores.json`.
See the README and exchange contract for exact JSON structures.

## Preview artifacts

All previews use the local DMC5 source. The GTA6 appearance is explicitly a theme demonstration,
not GTA6 gameplay or a GTA6 recognition test. The only source interval extracted was 30 seconds
starting at 4297s; the complete recording was not scanned/rendered. The short lossless fixture
decodes differently from the original recording and is not a long-video performance proxy.

- [Six-second before/after comparison](output/universal-upgrade/before-after.mp4)
- [Comparison still](output/universal-upgrade/before-after.jpg)
- [Action/funny/cinematic presentation still](output/universal-upgrade/preset-comparison.jpg)
- [New matched six-second Short](output/universal-matched-final/short.mp4)
- [Eight-second explicit slow-motion/replay example](output/universal-effects-final/short.mp4)
- [Final automatic six-second Short](output/universal-engine-final/clips/short-01.mp4)
- [Final HTML report, including audio warnings](output/universal-engine-final/index.html)
- [Candidate exchange example](output/universal-engine-preview-v1/exchange/candidates.json)
- [Reviewed preset/hook/HUD/effect preview report](output/universal-engine-preview-v1/index.html)

The two-column comparison scales each video to 540x960 and includes the new video's audio
once. Use the full-resolution Shorts for quality assessment. The three-preset still compares
presentation on the same frame, not different semantic classifications or narrative edits.

## Validation

Baseline: **72 tests passed** before implementation. Final suite: **99 tests passed**,
including 27 new tests for contrast, quiet scenes, menus/transitions, source boundaries,
presets/uncertainty, theme independence, pattern diversity, HUD/punch protection, camera
widening, safe hook/reaction placement, speed/replay mapping, effect validation, audio
silence/clipping/join checks, review round trips, external-score validation and legacy CLI.
Existing tests exercise changed-code resume rejection, same-code resume, interrupted renders,
artifact preservation, checksum protection, no-network execution and original renderer pixels.

```powershell
python -B -m unittest discover -s workflows/gaming-shorts/tests -p "test_*.py"
```

The final automatic six-second Short passed full decode, metadata, sampled frame composition,
stream timing, audio alignment and source-integrity verification. A matching-code resume
took **0.915s**, rendered nothing and reused analysis, selection, previews and the checksummed
completed video. Its metrics retain the initial render as the first historical run.

The eight-second example explicitly slows source-relative 2–3s to half speed with audio
stretch, then replays 3–4s immediately after that interval. It contains 240 frames at 30fps.
QA checks include both speed/replay joins, output-tail synchronization and repeated-frame
composition. All sampled audio correlations exceeded 0.99. Its audio scan found no near-full-
scale samples or unexpected silence; it did flag clip-edge energy for listening review.
Punch-in requests remain constrained by protection; a fully protected wide frame can suppress
the punch. The example is a timing/mechanical test, not a claim that those timestamps identify
an exciting event.

A local external-score fixture was imported on resume, reranked the pending selection and
preserved original score/evidence. Its provider label explicitly says it is a manual test,
not ML. A subsequent review imported funny preset, manual hook, reaction, HUD protection and
a timed punch; previews regenerated while analysis stayed cached. No external hook suggestion
was automatically applied. The generated review-page JavaScript passed `node --check`.
This is syntax/backend integration verification; no full interactive browser test was run.

## Measured performance and selection comparison

All videos are 1080x1920 at the original 30fps, libx264 medium/CRF18, four encoder threads,
two OpenCV threads, AAC192k. The baseline renderer used the pre-upgrade implementation.
The matched after render uses the identical source frame interval and framing configuration,
with the new manual hook and GTA6 glow treatment. These are individual trials, not a
controlled statistical estimate; background load and encoder complexity can change timings.

| Measurement | Baseline, 6s | Matched upgraded, 6s | Explicit effects, 8s |
|---|---:|---:|---:|
| Render wall time including encoder finalization | 22.813s | 16.121s | 19.956s |
| Output frames | 180 | 180 | 240 |
| Render throughput | 7.89fps | 11.17fps | 12.03fps |
| Python render CPU seconds | 29.266 | 21.781 | 28.125 |
| Encoder CPU seconds | 53.969 | 38.297 | 44.125 |
| Python peak including QA, MiB | 251.91 | 247.03 | 250.15 |
| MP4 bytes | 8,722,857 | 8,853,878 | 10,573,409 |

The matched trial measured 6.692s less render time (29.3%), but this does **not** establish a
general speedup. Baseline and upgraded scenes differ in text/glow; system state varied, and
no long-recording benchmark was run. Python memory excludes FFmpeg/FFprobe child processes.
The optional effects trial adds two output seconds and additional join/audio QA; it is not
a like-for-like speed comparison. No GPU acceleration claim is made.

The full automatic smoke workflow changed from **41.072s** baseline to **30.049s** upgraded,
including analysis, six contact-sheet alternatives, render and QA. This workflow selected
different source bounds, so those totals are also observational. On the same 30-second fixture:

| Selection | Before | After |
|---|---|---|
| Qualifying candidates | 5 | 6 |
| Selected source interval | 6.9–12.9s | 7.0–13.0s |
| Heuristic score | 0.61909 | 0.62071 |
| Pattern / suggestion | Not reported | Sustained / action, 0.85 heuristic confidence |

Scores use different formulas and are not entertainment measurements. More candidates or
a higher score does not prove better Shorts. No audience-retention or view-count experiment
was performed. Candidate export on six candidates took 4.590s in a separate analysis-only
trial; this optional decoding cost is absent from normal generation.

Raw metrics: [baseline](output/universal-baseline-auto/metrics.json),
[matched after](output/universal-matched-final/metrics.json),
[effects](output/universal-effects-final/metrics.json),
[automatic run/resume history](output/universal-engine-final/metrics.json).
Final test log: [tests-final.log](output/universal-upgrade/tests-final.log).

## Limitations and compatibility

- Activity/audio cannot identify missions, humor, dialogue completion or payoff. Animated
  menus/cutscenes can still qualify; subtle static dialogue can be missed. Manual review matters.
- Only DMC5 footage was available. GTA6/HUD behavior was not validated against actual GTA6
  captures. Protected rectangles must match the user's recording; none are hard-coded for GTA6.
- No automatic internal cuts, subtitles/transcription, semantic hooks, scene-specific audio
  recognition, optical-flow interpolation or ML model were added. The future provider
  interface is implemented as local metadata/score/hook-suggestion exchange only.
- Effects use explicit source-relative intervals and frame snapping. Reaction captions use
  output time. Replay inserts immediately after its source interval; complex arbitrary edit
  sequencing is outside this version. Slow motion repeats frames and may look less smooth
  on low-frame-rate footage. Audio tempo adjustment is pitch-preserving, not lossless.
- Source min/max durations remain honored; explicit replay/slow motion can make output longer,
  capped at 180 seconds. Effects of the same type cannot overlap. Captions/overlays may be
  omitted to preserve gameplay and safe margins. HUD safety can suppress zoom emphasis.
- Audio clipping/edge warnings are heuristics, not mastering guarantees. Synchronization is
  checked at bounded windows and cannot prove every sample is correct.
- Existing source restrictions remain: local MP4, compatible CFR SDR BT.709 video, supported
  aspect/timeline and an original audio track. No silent substitution or source rewriting.
- New settings/code intentionally invalidate old run signatures. Use a new folder for this
  upgrade. Existing CLI arguments and legacy single-clip configurations remain supported;
  old completed files are preserved. Matching-code resume remains functional.

## Recommended commit (not created)

```text
feat(gaming-shorts): add adaptive editing presets and GTA 6 visual theme

Extend generic activity scoring with onset, contrast and quieter-scene evidence,
context-aware boundaries and quality-weighted temporal/pattern diversity.

Add uncertain-aware editing suggestions, manual hooks, protected HUD regions,
adaptive text placement and restrained pink/violet GTA6 presentation through
the existing configuration and HTML/JSON review workflow.

Support explicitly timed punch-ins, slow motion, replay and reaction captions
with shared frame/audio timelines and original audio preserved by default.
Add streaming audio diagnostics and edited-output synchronization checks.

Provide versioned local candidate/frame export and validated optional external
score imports without network calls, model downloads or paid dependencies.
Preserve source integrity, bounded processing, existing CLI and same-code resume.

Validate with 99 tests, short DMC5 theme demonstrations, audio/video QA, matched
render measurements and cached resume checks. Document limits and measured costs.
```
