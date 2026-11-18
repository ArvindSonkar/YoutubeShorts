# Cinematic title upgrade validation

Validated locally on 2026-11-18. No full recording was rendered, no services or models were
called, and no dependencies or fonts were downloaded. No commit or push was made.

## Result and preview

The small upper-left badge is replaced by a centered title with a separate optional subtitle.
The sample uses Segoe UI Bold, white primary text, a violet accent underline, softly tinted
secondary text, a soft shadow and the existing short fade. The source-driven moving blur,
outer rounded panel, glow, shadow, framing selection and audio handling remain in place.

- [Six-second side-by-side video](output/title-upgrade-comparison/before-after.mp4)
- [Before/after still](output/title-upgrade-comparison/before-after.jpg)
- [Full-resolution new Short](output/title-upgrade-after-v1/short.mp4)
- [Full-resolution old badge Short](output/title-upgrade-before-v1/short.mp4)
- [New frame](output/title-upgrade-after-v1/frame.png)
- [New layout measurements](output/title-upgrade-after-v1/layout.json)
- [Technical video/audio verification](output/title-upgrade-after-v1/qa.json)

The before video was rendered with the old badge implementation before the title code was
changed. Both benchmark jobs use frames 207 through 386 of the existing 30-second combat
excerpt, 180 frames at 30fps, 1080x1920, libx264 medium/CRF18/4 encoder threads and AAC192k.
Both use two OpenCV threads. The after job adds the subtitle and current panel defaults.
The comparison video scales each sample to 540x960 and uses the after video's audio once.
The original full-resolution videos are the quality references.

## Composition and controls

At 1080px wide, the title uses a 96px target font for cinematic style, a 44px minimum,
up to three lines and a 28px subtitle. Minimal targets about 62px; bold about 113px.
Actual sizes depend on the available width and height. Longer titles wrap and shrink;
overlong unbroken words split. No title text is silently truncated. When text cannot fit
at the minimum size, the optional layer is omitted instead of covering gameplay.
Subtitles can wrap to two lines and are omitted before giving up on the primary title.
All sizes scale with output resolution. Local custom fonts can be supplied.

The title is centered on the canvas, inside the symmetric part of the configured safe
rectangle. At 1080x1920 the default safe rectangle is x=60..907, y=154..1536; the title
layer occupies x=173..907 and is centered at x=540. In this sample its y range is 272..558,
above the gameplay panel's y=658 upper edge. Placement uses the shared empty band over
the entire clip, so changing framing does not make text jump. Near-full-height crops
still disable decorations. Safe margins are configurable design estimates; platform
controls vary and these margins do not guarantee that YouTube controls avoid source HUDs.

The sharp gameplay image grows from 1008px to 1036px wide: about 2.8% wider and 5.6% more
area. Margin changes from 24px to 12px; requested padding changes from 12px to 8px. The
rounded-corner safety calculation raises actual inset to 10px where needed. No additional
source pixels are cropped. Filling substantially more vertical space with a landscape
source would require changing crop/framing policy, so the background remains visible.

Themes `generic`, `dmc5`, `gta5`, `gta6` and `custom` provide names/colors, using the same
typesetter. DMC5 is violet, GTA5 green and GTA6 pink. `--game-title` overrides the theme name;
`visual.accent` overrides its RGB color. Generic/custom do not invent a game title.

New options:

```text
--title-style minimal|cinematic|bold
--subtitle "CINEMATIC GAMEPLAY"
--game-title "YOUR GAME NAME"
--theme generic|dmc5|gta5|gta6|custom
```

`--title-style cinematic` is the default. Existing flags still work. `--visual-style original`
still selects the original composition; title styles apply to cinematic composition.
Subtitles are empty by default. The settings file can override the following values:

```json
{
  "visual": {
    "theme": "dmc5",
    "fade_in": 0.35,
    "title": {
      "style": "cinematic",
      "subtitle": "CINEMATIC GAMEPLAY",
      "font": "C:/Windows/Fonts/segoeuib.ttf",
      "font_size": 96,
      "min_font_size": 44,
      "max_lines": 3,
      "subtitle_size": 28,
      "letter_spacing": 1.5,
      "shadow_opacity": 0.55,
      "shadow_blur": 3,
      "underline": true,
      "uppercase": true
    }
  }
}
```

Use `fade_in: 0` to disable the overlay fade. Typography layers are prepared once per job
and reused by sequential rendering and random-access preview/QA. Font checksums are included
in run identity. Legacy configurations without the new title section receive defaults.
Explicit saved panel settings remain honored. Start a new output folder after this code
upgrade; old code signatures deliberately cannot resume under changed renderer code.

Example for a later full run (provided only, not executed):

```powershell
python -B workflows\gaming-shorts\auto_shorts.py `
  --input "videos\DMC5.mp4" `
  --output-dir "output\dmc5-premium-titles-15" `
  --count 15 `
  --theme dmc5 `
  --title-style cinematic `
  --subtitle "CINEMATIC GAMEPLAY" `
  --offline
```

## Tests and integration

`python -B -m unittest discover -s workflows/gaming-shorts/tests -p "test_*.py"`
passed all **72 tests**, including 14 new title tests. New coverage includes long names,
unbroken names, font fitting, resolution scaling, all three styles, subtitle hierarchy and
omission, tight spaces, asymmetric safe zones, varying gameplay geometry, theme/custom
configuration, panel sizing, legacy defaults, font checksums, invalid values and review
round trips. Existing tests cover preservation of the selected gameplay edges, original
renderer pixel equality, deterministic previews, source integrity, audio checks and resume.

The final six-second encoded Short passed full decode, metadata/frame checks and audio
alignment checks. Audio correlation was above 0.9996 at both sampled offsets.
Source integrity checks passed. The before sample also passed technical QA.

A real CLI smoke run analyzed only the existing 30-second excerpt and created one six-second
candidate and contact sheets in `output/title-upgrade-auto-preview-v1`. No video was rendered
by this analysis-only run. It accepted the new title/subtitle CLI flags. A review JSON import
changed the pending title style to bold, preserved its supplied title/subtitle, regenerated
previews and reused cached analysis. The generated review-page JavaScript passed `node --check`.
This is syntax/integration verification, not a full interactive browser test.

## Measured rendering impact

| Measurement | Before badge | After title |
|---|---:|---:|
| Render wall time, including encoder finalization | 12.937s | 16.068s |
| Render throughput | 13.91fps | 11.20fps |
| Total benchmark wall time, including previews/QA | 22.309s | 25.099s |
| Python render CPU time | 18.609s | 20.984s |
| FFmpeg encoder CPU time | 39.016s | 40.266s |
| Python peak bytes at end of render | 128,040,960 | 130,580,480 |
| Python process peak bytes including QA | 257,736,704 | 256,884,736 |
| Encoded MP4 bytes | 8,360,760 | 8,712,312 |

The measured render increase is **3.131s / 24.2%**; total benchmark time rises about 12.5%.
These are single matched trials on this machine, not a statistical speed estimate. The
measurement includes the larger gameplay panel and subtitle as well as primary typography;
it does not isolate each effect. System load and encoder variability affect wall time.
Python memory excludes FFmpeg/FFprobe children; CPU seconds can exceed elapsed time due
to threading. No long-recording performance or view-count improvement is claimed.

Raw data: [before metrics](output/title-upgrade-before-v1/metrics.json),
[after metrics](output/title-upgrade-after-v1/metrics.json).

## Implementation files

- `title_layout.py`: generic responsive title typesetting, styles, shadow and underline.
- `visuals.py`: adaptive title placement, safe composition, GTA6/custom themes and title-font binding.
- `auto_shorts.py`: CLI options, review application and code-signature inclusion.
- `review.py`: title/style/subtitle review controls and validation.
- `defaults.json`, `auto_defaults.json`, `cinematic-example.json`: title settings and panel defaults.
- `tests/test_titles.py`: 14 new automated tests.
- `tests/test_visuals.py`: updates the overlay contract from badge to title.
- `tests/benchmark_titles.py`: bounded 2-12 second benchmark helper.
- `README.md` and this report: configuration and measured results.

These changes sit on top of the pre-existing uncommitted cinematic/progress upgrade.
Suggested commit title, if the user later chooses to commit:

```text
feat(gaming-shorts): enhance cinematic title typography and adaptive layout
```
