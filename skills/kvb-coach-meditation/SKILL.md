---
name: kvb-coach-meditation
description: >
  Short meditation with generative alpha-wave music, animated fractals and
  breathing cues, tuned by feedback. Trigger on /kvb-coach-meditation.
---

A short session in the browser: `assets/meditation.html` plays generative
ambient music over an alpha-wave layer (8–13 Hz) and animates a Julia fractal
that breathes with the cue. It runs locally, without audio files or network.

`${CLAUDE_SKILL_DIR}/scripts/meditation.py` keeps the settings in the
gitignored `.state/meditation.json` of the skills repository and writes the
session page with the settings embedded:

```bash
meditation.py --state <skills repo>/.state/meditation.json set <key>=<value> ...
meditation.py --state <same> show
meditation.py --state <same> session --page ${CLAUDE_SKILL_DIR}/assets/meditation.html --out <skills repo>/.state/meditation-session.html
```

| Key | Values | First session |
| --- | --- | --- |
| `minutes` | 1–30 | 5 |
| `beat` | 8–13 Hz | 10 |
| `base` | 100–400 Hz | 196 |
| `volume` | 0.05–1 | 0.4 |
| `mode` | `isochronic` (speakers), `binaural` (headphones) | `isochronic` |
| `palette` | `aurora`, `ocean`, `ember`, `forest` | `aurora` |
| `breathing` | `box` (4-4-4-4), `478`, `none` | `box` |

## Step 1: start

Without a state file, `set` the first-session values. Write the session page
and hand the operator `xdg-open <session page>` to run: inside the agent
sandbox `xdg-open` and `gio open` exit 0 without opening anything. The page starts on the
operator's click, shows the elapsed time as a line growing along the bottom
edge, and fades out after the set minutes; `+` and `-` set the
picture's brightness (20–160 %), which the browser keeps for the next session.

## Step 2: feedback

After every session, run the `kvb-think-listen` skill with one
`AskUserQuestion`, `multiSelect: false` per question: music (calmer, fits,
livelier, quieter, louder), picture (fits, calmer, other palette), length
(shorter, fits, longer), effect (calmer, more focused, nothing, restless).
Ask about headphones once before switching to `binaural`.

## Step 3: optimize

One `set` per answer: quieter or louder ±0.1 `volume`; calmer music `beat`
−1, more focus `beat` +1; shorter or longer ±2 `minutes`; other palette the
next one; restless `breathing=none`. Log the session in the `kvb-coach`
profile (`coach.py done psyche "Meditation <n> min"`) and a liked effect with
`coach.py like psyche`.
