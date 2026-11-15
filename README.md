# html-slides

An agent skill that builds **narrated, video-style slide decks as a single HTML file**.

Press play and the deck narrates itself with the browser's built-in speech, reveals each element as it is spoken, shows captions, and advances on its own, like an explainer video. Pause it and it is an ordinary 16:9 slide deck you page through with the arrow keys, like PowerPoint. There is no video file, no server and no build toolchain: the result is one `.html` file that opens by double-click.

It is written for [Claude Code](https://claude.com/claude-code) and other agents that read the `SKILL.md` format. The skill is used mostly for Japanese decks, so the bundled samples are Japanese; decks can be written in any language.

## What a deck does

- **Narration** with the viewer's on-device voice (Web Speech API), sentence by sentence, with captions.
- **Reveal on cue**: an element carrying `data-say="…"` appears when its narration is spoken.
- **Video-style controls**: play / pause, a progress bar with one segment per slide, speed, sound, captions, full screen.
- **Slide overview**: a thumbnail grid to jump to any slide.
- **Fixed 16:9 stage** scaled to the window; keyboard, click, tap and swipe navigation.
- **Phones**: captions move below the slide when the phone is held upright.
- **Print to PDF**: one slide per page.
- **Ten themes**, plus a **dense mode** for information-heavy business documents: conclusion line, titled boxes, comparison tables with ○ / △ / ×, schedule (Gantt-style) tables, source notes, a footer with a confidentiality label and page numbers.
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

`--shots` saves a PNG of every slide and two phone views. `--extract` recovers the source from a built deck, which also lets an old deck be rebuilt with the current player.

| File | Role |
|---|---|
| `skills/html-slides/SKILL.md` | instructions for the agent |
| `skills/html-slides/references/layouts.md` | every layout, with copy-paste examples |
| `skills/html-slides/references/dense.md` | dense mode and the business components |
| `skills/html-slides/assets/template.html` | the player (CSS and JavaScript, no dependencies) |
| `skills/html-slides/assets/starter*.slides.html` | sample sources |
| `skills/html-slides/scripts/build.py` | lint, assemble, check |
| `skills/html-slides/scripts/check.py` | rendered check and screenshots |
| `skills/html-slides/scripts/add_voice.py` | optional: embed locally generated audio (VOICEVOX / AivisSpeech, Japanese) |

## Narration and privacy

Narration uses the voice installed on the viewer's device, so its quality depends on the device, and a device with no on-device voice for the deck's language plays captions only. This is deliberate. Browsers also offer online voices that sound better, but they send the text to a server, and the player never selects them.

If you want a consistent voice, `add_voice.py` can generate audio on your own computer with a VOICEVOX-compatible engine and embed it in the HTML. It refuses to connect to anything other than `127.0.0.1`.

## Tests

```sh
python3 tests/run_tests.py
```

About 110 checks: the lint, every example in the documentation, both sample decks in all ten themes, the source round trip, PDF page count, a scripted interaction test in a headless browser (play, pause, navigation, overview, replay), and narration tests against a fake speech engine that delivers its voice list late, drops notifications and fails.

The playback state machine is also specified in TLA+ ([`tests/tla/Player.tla`](tests/tla/Player.tla)) and model-checked with TLC. It verifies, among other things, that exactly one thing can advance playback at any time, that playback can always move on by a timer even if the speech engine never reports back, and that nothing changes while paused. Model checking found a real defect (an engine that never starts speaking kept being retried forever instead of falling back to captions), which is now covered by a browser test as well. To run it, point `TLA_JAR` at `tla2tools.jar`:

```sh
TLA_JAR=/path/to/tla2tools.jar tests/tla/run.sh
```

## Known limits

- Developed and tested with headless Chrome on macOS. Behaviour on real Windows, iOS and Android devices, and how real voices sound, has not been verified by the author.
- The checks measure layout with the fonts of the machine that builds the deck; a line that just fits there can wrap on another system.
- Dense slides cannot be read on a phone held upright.
- The checks cannot judge the content: whether the narration flows, or whether a model added statements that were not in the material it was given.

## License

[MIT](LICENSE)
