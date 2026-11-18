# Wuthering Waves: verified Shorts analysis

**Production update, 9 November 2026:** The highest-ranked clip has now been rendered to [mourning-thunder-final.mp4](shorts/mourning-thunder-final.mp4) and verified with portable FFprobe. See [render verification](shorts/render-verification.md). The analysis below records the earlier selection stage; its statements about unavailable standalone tools and an unrendered clip describe that earlier stage.

Analyzed 9 November 2026 (Asia/Calcutta) using **yt-shorts**, **yt-edit**, and **yt-seo**. This replaces the earlier metadata-only report.

**Test the finishing sequence first:** it resolves the fight and ends with a visible “Challenge Complete” banner. Two additional clips feature crossing purple beams and an opening exchange with successive cinematic attacks.

## Source and technical checks

Source: `videos/Wuthering Waves Mourning Thunder Difficulty_ 5 Defeated l PS5.mp4`.

Associated upload: https://www.youtube.com/watch?v=IqhzjzsTLaE — “Wuthering Waves Mourning Thunder Difficulty: 5 Defeated l PS5,” Avi Fantasy Gaming (metadata verified in the previous pass). Clip observations and timestamps below come from the local footage.

| Property | Verified result |
| --- | --- |
| Size | 59,794,869 bytes |
| Container duration | **218.964131 seconds / 03:38.964** |
| Video duration | 218.952286 seconds |
| Resolution | **1280 × 714**, slightly wider than 16:9 |
| Video codec | H.264 / `avc1` |
| Frame rate | **29.97 fps**, constant: 11,988 track ticks/second, 400 ticks/frame |
| Frame count | 6,562 |
| Audio | **One** audio track; `mp4a` sample entry declares **2 channels at 44,100 Hz** |
| Audio duration | 218.964172 seconds |
| FFmpeg / FFprobe commands | Neither found on PATH or in checked common installation locations |
| Available local tools | Existing OpenCV 4.13.0 with its **FFMPEG decoding backend**, Pillow, Python |

Checked common locations included C:/ffmpeg, C:/Program Files/ffmpeg, WinGet packages/links, Scoop apps, and Chocolatey's bin directory when present. This was not an exhaustive search of every drive. OpenCV's bundled FFmpeg decoder is available even though the standalone commands were not found.

Audio properties are container declarations. Audio was **not listened to, decoded for analysis, or transcribed**; the specific mp4a subtype was not independently verified. No claims about narration, music, loudness, or sound quality follow from the stream metadata.

Source SHA-256 before and after extraction:

```text
7b171b7d822d660ef46d2e926bccf9ffd5f79ff71ac8f458a11ac019884c9819
```

## Inspection and time accuracy

Inspected locally decoded frames every five seconds across the recording, then every second through 00:08–00:34, 02:17–02:46, and 03:08–03:32. Additional quarter-second samples covered the opening evasive movement and selected cut boundaries. This is actual footage inspection through contact sheets, **not continuous audiovisual playback**; brief events between samples may be missed.

Evidence: [frames and contact sheets](frames/), [technical metadata](video-metadata.json), and [local extraction script](inspect_video.py). Frame-index JSON files accompany the images.

MP4 sample durations, composition offsets, and the video edit list were checked: presentation timestamps form a regular grid starting at zero, one frame per 400/11,988 seconds. OpenCV returned the requested frame indexes.

Times are **elapsed local-file time, MM:SS.mmm**, rounded to milliseconds. Zero-based frame indexes are authoritative. In points are inclusive; out points are exclusive. These are editorial cut boundaries, not claims that an attack begins at an exact millisecond. Do not use the in-game countdown as the media clock: it pauses during some cinematics. The local runtime matches YouTube's rounded 219 seconds, but frame-for-frame identity with the online upload was not checked.

## Ranked selections

| Rank | Moment | Start | End | Duration | Frames [in, out) |
| --- | --- | --- | --- | --- | --- |
| 1 | Final exchange → Challenge Complete | **03:09.990** | **03:30.511** | **20.521 s** | 5694–6309 |
| 2 | Purple beams → cinematic impact | **02:18.505** | **02:38.759** | **20.254 s** | 4151–4758 |
| 3 | Opening evasion → successive attacks | **00:08.008** | **00:24.758** | **16.750 s** | 240–742 |

All are contiguous source selections at normal speed. Durations exclude any added replay, freeze, or intro card. Ranking is editorial judgment, not a performance forecast.

## 1. Final exchange → Challenge Complete

**Verified observations:** A bright purple impact fills the boss area at 03:09.990. The player moves across the arena during the still-active encounter at 03:12.993–03:14.995. A red/purple sweeping effect appears at 03:20.000, followed by a character close-up at 03:21.001 and blue circular attack effects at 03:22.002–03:23.003. Late attacks continue through sampled 03:25–03:27 frames. By 03:28.008 the boss is no longer visible in that frame. “Challenge Complete” is readable at 03:29.743 and remains visible at 03:30.244.

Evidence: [combat](frames/finish_sheet_01.jpg), [payoff](frames/finish_sheet_02.jpg), [in boundary](frames/finish_start_sheet_01.jpg), [out boundary](frames/finish_end_sheet_01.jpg).

**Why engaging:** immediate spectacle, continuing resistance, a final attack sequence, and a clear result. The completion banner makes this the strongest standalone story.

**New hook:** “Can you spot the last attack before Mourning Thunder finally goes down?”

**First-two-second overlay:** `DIFFICULTY 5 · FINAL EXCHANGE`

**Edit:** keep all 20.521 seconds at 1×, starting directly on the purple impact. Preserve 03:20–03:27 and the brief gap before the completion banner so the payoff reads. End before most of the fade and reward-menu tail. Do not imply that one move caused all the remaining damage. Retain original audio provisionally; listen before placing sound edits. Optional narration should sit over the opening footage, with game audio ducked only underneath it.

**9:16:** preserve the wide combat view inside a vertical canvas. Briefly use a tracked close-up at the 03:21 cinematic, then return wide. Keep the entire completion text visible; a static center crop would truncate it. Put added text outside the boss-health and completion-banner areas.

**Loop:** cut from the readable completion banner back to the opening purple impact. This is a deliberate replay loop, not seamless continuous action.

```text
Title: Mourning Thunder Defeated! Difficulty 5 | Wuthering Waves

Description:
Wuthering Waves Mourning Thunder, Difficulty 5: the final exchange and Challenge Complete.
PS5 gameplay from Avi Fantasy Gaming, with the finishing sequence kept in order.
Full fight: https://www.youtube.com/watch?v=IqhzjzsTLaE

Hashtags: #WutheringWaves #MourningThunder #PS5 #Shorts
```

## 2. Purple beams → cinematic impact

**Verified observations:** A large dark-purple electrical effect expands at 02:18.505–02:20.007. Bright purple/pink lines cross the scene at 02:24.011–02:27.014 while the player remains in combat. A character close-up appears at 02:29.016–02:30.017. Another attack close-up at 02:36.990–02:37.491 resolves into a bright impact and visible damage number at 02:37.758–02:38.258.

“Beams” describes the visible lines; exact mechanic and ownership were not established.

Evidence: [beams](frames/lasers_sheet_01.jpg), [follow-up](frames/lasers_sheet_02.jpg), [in boundary](frames/lasers_start_sheet_01.jpg), [impact boundary](frames/lasers_end_sheet_01.jpg).

**Why engaging:** the electrical burst establishes immediate visual tension, crossing lines add complexity, and the later attack has a readable payoff without requiring a boss kill.

**New hook:** “Where would you move before Mourning Thunder fills the arena with purple beams?”

**First-two-second overlay:** `WATCH THE CROSSING BEAMS`

**Edit:** retain the source order and normal speed for the 20.254-second version. Keep the beam geometry visible and end just after the cinematic impact. Avoid adding flashes or transitions over already busy footage. Do not label this a dodge tutorial, no-damage sequence, or defeat clip. No dead-air cut is justified from the frames; quiet gameplay can carry action. Sound accents remain provisional until audio is heard.

**9:16:** use full-width gameplay within a vertical canvas during the arena effects. A narrow crop removes the outer beam paths. Brief cinematic close-ups can fill the vertical frame, but return wide before the payoff. Put the hook in unused canvas space.

**Loop:** cut the bright final impact back to the dark-purple opening effect. This visual contrast is an editorial loop, not a verified seamless match.

```text
Title: Mourning Thunder's Purple-Beam Chaos | Wuthering Waves

Description:
Wuthering Waves Mourning Thunder gameplay with purple beams crossing the arena.
This Difficulty 5 PS5 exchange runs through the beam effects into a cinematic attack payoff.
Full fight: https://www.youtube.com/watch?v=IqhzjzsTLaE

Hashtags: #WutheringWaves #MourningThunder #BossFight #Shorts
```

## 3. Opening evasion → successive attacks

**Verified observations:** At 00:08.008–00:09.009, the player moves low and laterally as the boss approaches. Purple sweeping effects appear at close range at 00:09.243–00:10.511. A character close-up at 00:13.013 leads into a broad purple effect at 00:15.015 and further exchanges. Another close-up at 00:19.987 leads into blue circular effects at 00:20.988–00:22.990. Impacts and damage numbers continue at 00:23.257–00:24.491, followed by a green sweeping effect. The out point precedes the purple vertical strike visible at 00:24.992.

The movement supports describing evasion; it does **not** establish a perfect dodge, parry, no-hit exchange, or mechanically uninterrupted combo.

Evidence: [opening sequence](frames/opening_sheet_01.jpg), [movement samples](frames/evade_sheet_01.jpg), [out boundary](frames/opening_end_sheet_01.jpg).

**Why engaging:** a readable approach and evasive movement lead into two close-ups and contrasting purple/blue attacks. It is compact and visually varied, though less conclusive than the finishing clip.

**New hook:** “Would you back off before Tempest Mephis swings, or stay close for the combo?”

“Combo” is editorial shorthand for successive attacks, not a verified input chain.

**First-two-second overlay:** `BACK OFF OR KEEP ATTACKING?`

**Edit:** keep the complete 16.750 seconds at 1×. Exclude the challenge-selection menu and setup. Let the game's cinematic transitions set the pace; added transitions would obscure the attacks. End after the blue/green sequence resolves, before the next purple strike. Do not slow the movement and label it a perfect dodge. Any added freeze or replay requires recalculating runtime.

**9:16:** preserve wide framing for 00:08–00:12 and the broad effects. Brief face-centered crops can emphasize the close-ups near 00:13 and 00:20. Reframe each shot separately; the player and boss do not stay at a single horizontal coordinate.

**Loop:** the late lateral movement can cut back to the opening movement. Similar direction can help the replay, but a seamless match has not been verified.

```text
Title: Tempest Mephis Opening Combo | Wuthering Waves PS5

Description:
Wuthering Waves Tempest Mephis opening combo: evasive movement followed by purple and blue attack sequences.
Mourning Thunder Difficulty 5 gameplay on PS5, kept in its original order.
Full fight: https://www.youtube.com/watch?v=IqhzjzsTLaE

Hashtags: #WutheringWaves #TempestMephis #PS5 #Shorts
```

## Shared vertical framing guidance

A full-height 9:16 crop retains only about **31% of the source width**. An exact-ratio example is **396 × 704**, centered at **x=442, y=5** on the source. This is a geometric example, not a validated tracking path. It removes side HUD elements and can separate the player from the boss.

Default recommendation: a **1080 × 1920 canvas**, with the complete source fitted to approximately **1080 × 602** over a dark background. Place the hook above the gameplay and a context label below. This preserves spatial information but makes gameplay smaller on a phone. Use brief tracked cinematic crops for variety and inspect every transition before rendering. Upscaling does not add source detail.

The opening menu shows Difficulty V; the boss HUD identifies Tempest Mephis: Mourning Thunder. No character or skill names were added where not independently verified. Avoid claims of damage records, perfect dodges, no-hit clears, or specific mechanics.

## Skill checks and search copy

All three final proposed hooks were scored with `.agents/skills/yt-script/hookscore.py`: **58/100, WORKABLE** each. Generic versions for clips 2 and 3 scored lower and were revised to name the encounter. This heuristic checks wording, not expected views. Hooks are proposed new narration or text, not quotes from the source.

These are primarily feed-oriented highlights. Search copy supplies context; no search-volume or trend research was performed.

| Clip | Three target search queries | Title/opening-description check |
| --- | --- | --- |
| 1 | Wuthering Waves Mourning Thunder; Mourning Thunder Difficulty 5; Mourning Thunder PS5 | Game, encounter, difficulty and platform are present. |
| 2 | Wuthering Waves Mourning Thunder; Mourning Thunder purple beams; Mourning Thunder Difficulty 5 | Game, encounter, beam wording and difficulty are present. |
| 3 | Wuthering Waves Tempest Mephis; Tempest Mephis opening combo; Mourning Thunder PS5 | Game, boss, combo, encounter and platform are present. |

The yt-edit dead-air/filler script was not run: there is no timestamped transcript, and speech-gap logic cannot establish whether a gameplay section is expendable. This report supplies visual edit decisions instead.

No voice profile was found at the previously checked `~/.claude/youtube/voice.md`. With no commentary heard, the drafts use plain gaming language rather than claiming to match an established creator voice. No profile was created.

## Limitations and completion status

- Footage frames were decoded and inspected locally. Continuous audiovisual playback, acoustic review, transcript analysis and retention data were unavailable in this pass.
- Precise frame boundaries do not imply certainty about attack ownership, exact hit timing, or dodge success.
- Crop strategies are recommendations; no vertical video was rendered or reviewed.
- No tools were installed, credits spent, media uploaded, or content published.
- The original video checksum remained unchanged. Only analysis artifacts under `output/` were created or updated.

```text
Recommended first experiment: final exchange -> Challenge Complete
In: 03:09.990 / frame 5694
Out: 03:30.511 / frame 6309, exclusive
Duration: 20.521 seconds
Keep the source order and the completion banner.
Use clip 1's title, description and hashtags.
Analysis complete; no video has been rendered or published.
```

Draft feedback only; no publishing authorization is requested: **ship it, or change it?**
