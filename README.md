# html-slides

An agent skill that builds **narrated, video-style slide decks as a single HTML file**.

Press play and the deck narrates itself with the browser's built-in speech, reveals each element as it is spoken, shows captions, and advances on its own, like an explainer video. Pause it and it is an ordinary 16:9 slide deck you page through with the arrow keys, like PowerPoint. There is no video file, no server and no build toolchain: the result is one `.html` file that opens by double-click.

It is written for [Claude Code](https://claude.com/claude-code) and other agents that read the `SKILL.md` format. The skill is used mostly for Japanese decks, so the bundled samples are Japanese; decks can be written in any language.

## What a deck does

- **Narration** with the viewer's on-device voice (Web Speech API), sentence by sentence, with captions.
- **Reveal on cue**: an element carrying `data-say="…"` appears when its narration is spoken.
- **Video-style controls**: play / pause, a duration-weighted progress bar with hover tooltips, elapsed / total clock, speed, sound, captions, full screen, hardware media keys (Media Session API), and Screen Wake Lock while playing.
- **Navigation & review**: thumbnail slide overview (`G`, arrow keys), searchable / copyable transcript panel (`T`, `/` to filter), sentence seeking (`↑` / `↓`), replay sentence (`R`), direct slide jump (`1`–`99`), presenter blackout (`B`), and keyboard shortcuts help (`?`).
- **Fixed 16:9 stage** scaled to the window; keyboard, click, tap and swipe navigation.
- **Phones**: captions move below the slide when the phone is held upright.
- **Print & CLI export**: print to PDF one slide per page (or `?notes=1` with speaker notes), plus one-command `--pdf` / `--pdf-notes`, Markdown `--script`, and WebVTT `--vtt` export from `build.py` / `check.py`.
- **Ten themes**, plus a **dense mode** for information-heavy business documents: conclusion line, titled boxes, comparison tables with ○ / △ / ×, schedule (Gantt-style) tables, source notes, a footer with a confidentiality label and page numbers.
- **Local images, single file**: write `<img src="photo.png" alt="…">` (`srcset` / `<picture>` or SVG `<image href="photo.png">`) in the source and `build.py` automatically embeds local PNG/JPEG/WebP/GIF/SVG/AVIF images as data URIs (with layouts for full-height figures, framed screenshots, text + image splits, photo cards, and full-bleed background photos).
- **Nothing leaves the machine**: no external resources are loaded, only voices the browser reports as on-device are used, and the page opts out of automatic translation.

## Try it

Open one of the built samples in a browser and press play:

- [`examples/password-rules.html`](examples/password-rules.html): a short training deck (dark theme).
- [`examples/tablet-proposal.html`](examples/tablet-proposal.html): a dense business proposal (corporate theme, footer and page numbers).

`skills/html-slides/assets/themes.html` shows every theme side by side.

## Install

As a Claude Code plugin (Claude Code 2.1.275 or later):

```
/plugin install html-slides --marketplace ifapmzadu6/html-slides
```

On older versions, add the marketplace first, then install:

```
/plugin marketplace add ifapmzadu6/html-slides
/plugin install html-slides@html-slides
```

Or copy the skill folder to where your agent looks for skills. For Claude Code:

```sh
git clone https://github.com/ifapmzadu6/html-slides
cp -R html-slides/skills/html-slides ~/.claude/skills/html-slides              # for every project
cp -R html-slides/skills/html-slides your-project/.claude/skills/html-slides   # or for one project
```

Then ask for a deck, for example: *"Make a narrated slide deck that explains our expense-claim process to new staff, about 7 slides."*

Requirements: Python 3.8 or later. The rendered check and the screenshots also need Chrome, Edge or Chromium; without one, the source lint still runs.

The player's own labels (buttons, start screen, notices) are in English. To localise them, add a block to `TEXT` in `assets/template.html`.

## How it works

The agent never touches the player. It writes a short source file, and a script assembles and checks the deck.

```html
<!--
title: 経費精算のやり方
theme: light
-->
<section class="slide title">
  <h1 data-say="経費精算のやり方を、三分で説明します。">経費精算の<br>やり方</h1>
</section>
<section class="slide">
  <h2 data-say="準備するものは三つです。">準備するもの</h2>
  <ul>
    <li data-say="一つ目は、領収書の写真。"><strong>領収書</strong>の写真</li>
    <li data-say="二つ目は、支払った日付と金額。">日付と金額</li>
  </ul>
</section>
```

```sh
python3 skills/html-slides/scripts/build.py deck.slides.html --shots deck-shots
```

`build.py` runs two checks and prints every finding with the source line number and a concrete fix, so that smaller models can converge on a clean deck by following the output:

1. **Source lint** (no browser): unknown class, attribute or theme names with "did you mean" suggestions, unclosed tags, slides without narration, external URLs, text sized too small.
2. **Rendered check** (headless browser): content outside the slide area or spilling out of its box, text rendered too small, captions that are too long, slides that run too long.

`--shots` saves a PNG of every slide and two phone views. `--pdf` exports a 16:9 PDF (add `--pdf-notes` for speaker-notes handout pages), `--script` exports the narration script as Markdown, `--vtt` exports timed captions as WebVTT, `--json` prints machine-readable build and check results, `--watch` rebuilds automatically on save, `--open` opens the built deck in a browser, and `--extract` recovers the source from a built deck (which also lets an old deck be rebuilt with the current player).

| File | Role |
|---|---|
| `skills/html-slides/SKILL.md` | instructions for the agent |
| `skills/html-slides/references/layouts.md` | every layout, with copy-paste examples |
| `skills/html-slides/references/dense.md` | dense mode and the business components |
| `skills/html-slides/assets/template.html` | the player (CSS and JavaScript, no dependencies) |
| `skills/html-slides/assets/starter*.slides.html` | sample sources |
| `skills/html-slides/scripts/build.py` | lint, assemble, check |
| `skills/html-slides/scripts/check.py` | rendered check and screenshots |
| `skills/html-slides/scripts/add_voice.py` | optional: embed locally generated audio (VOICEVOX / AivisSpeech, Kokoro-82M, or Qwen3-TTS) |

## Narration and privacy

Narration uses the voice installed on the viewer's device, so its quality depends on the device, and a device with no on-device voice for the deck's language plays captions only. This is deliberate. Browsers also offer online voices that sound better, but they send the text to a server, and the player never selects them.

If you want a consistent voice, `add_voice.py` can generate audio on your own computer with a VOICEVOX-compatible engine, Kokoro-82M (`--engine kokoro`), or Qwen3-TTS (`--engine qwen3` via PyTorch on Windows or MLX on Apple Silicon) and embed it in the HTML. Speech-engine API calls stay on the loopback interface. Model weights are downloaded on first use.

Qwen3 uses the source’s `lang` setting for pronunciation and `--speaker` for the voice. For example, `lang: en-GB` selects English synthesis. Changing the synthesis language regenerates the embedded clips the next time you run `add_voice.py`.

If a sentence has an unwanted sound after its final word, you can shorten that embedded clip. Supply the exact narration sentence and the time in seconds from the start of the clip:

```sh
python skills/html-slides/scripts/add_voice.py deck.html --trim-clip "気温は−5℃です。" 2.44
```

Choose the time by checking the individual clip. The edit applies everywhere that sentence is reused. The corrected clip is stored as PCM WAV. Trimming MP3 or M4A inputs requires ffmpeg (or `afconvert` on macOS). You can also run `add_voice.py deck.html --info` to inspect embedded audio details or `--dry-run` to preview narration sentences and Japanese pronunciation normalization (add `--json` for machine-readable output).

### Windows (PowerShell)

Use 64-bit Python 3.12 and Edge or Chrome. From the repository directory, build a deck and open it:

```powershell
py -3.12 skills/html-slides/scripts/build.py deck.slides.html --shots deck-shots
Start-Process .\deck.html
```

To embed Qwen3 narration, install the official PyTorch backend in a virtual environment. These commands use the CPU build:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install qwen-tts
.\.venv\Scripts\python.exe skills/html-slides/scripts/add_voice.py deck.html --engine qwen3 --speaker Ono_Anna
```

On a machine with an NVIDIA GPU, install the matching CUDA builds of PyTorch and torchaudio before installing `qwen-tts`. The script selects CUDA when PyTorch exposes it. Windows synthesizes one sentence per clip using the deck language and the same Japanese pronunciation rules as the Mac backend. The first run downloads the CustomVoice model. For an offline setup, pass its local directory with `--model`. The resulting HTML includes the audio and can be opened on another PC.

## Tests

```sh
python3 tests/run_tests.py
```

Over 400 checks: the lint (including setting typos/duplicates, Gantt column sums, duplicate IDs, `.voice` symbols, local `srcset` images, and self-closing HTML), every example in the documentation, both sample decks in all ten themes, WCAG AA contrast across all ten themes, `themes.html` interactive filters and keyboard accessibility, the source round trip, `--watch` auto-rebuild, PDF/notes, Markdown script and WebVTT export, JSON CLI contracts, `add_voice.py` engines/batch-alignment/trimming/normalization, a scripted interaction test in a headless browser (play, pause, sentence seeking, replay, digit jump, overview, IME-safe NFKC transcript search/clear, presenter blackout, shortcuts help, narrow-mobile layout, focus/inert accessibility, replay), embedded audio E2E playback/resume and fallback, and narration tests against a fake speech engine that delivers its voice list late, drops notifications and fails.

The playback state machine is also specified in TLA+ ([`tests/tla/Player.tla`](tests/tla/Player.tla)) and model-checked with TLC. It verifies, among other things, that exactly one thing can advance playback at any time, that playback can always move on by a timer even if the speech engine never reports back, and that nothing changes while paused. Model checking found a real defect (an engine that never starts speaking kept being retried forever instead of falling back to captions), which is now covered by a browser test as well. To run it, point `TLA_JAR` at `tla2tools.jar`:

```sh
TLA_JAR=/path/to/tla2tools.jar tests/tla/run.sh
```

## Known limits

- The browser regression suite runs on macOS and Windows. Physical iOS and Android playback and device-specific voices require separate testing.
- The checks measure layout with the fonts of the machine that builds the deck; a line that just fits there can wrap on another system.
- Dense slides cannot be read on a phone held upright.
- The checks cannot judge the content: whether the narration flows, or whether a model added statements that were not in the material it was given.

## License

[MIT](LICENSE)
