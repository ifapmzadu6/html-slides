---
name: html-slides
description: Build a narrated, video-style slide deck as one self-contained HTML file. Pressing play makes the browser read the narration aloud, reveals each element as it is spoken, shows captions, and advances automatically; paused, it works as a normal 16:9 slide deck with keyboard navigation, like PowerPoint. Opens by double-click on Windows, works on phones, prints to PDF. Use this skill whenever the user asks, in any language (it is used mostly for Japanese decks), for slides, a presentation, a deck, an explainer video, a narrated walkthrough, training or onboarding material, or "something like a video but in HTML, not mp4" - even if they do not say "HTML". Also use it for information-dense business documents such as meeting papers, monthly reports, approval requests, proposals and option comparisons (dense mode with comparison tables, schedule tables, a confidentiality footer and page numbers), and to edit a deck this skill built earlier. Do not use it when the user wants an actual .pptx file.
---

# html-slides - narrated, video-style HTML slide decks

Pressing play makes the deck narrate itself with the browser's built-in speech, reveal each element as its narration is spoken, show captions, and move to the next slide on its own. Paused, it is an ordinary slide deck you page through with the arrow keys. The deliverable is **one HTML file**.

The player (scaling, narration, captions, control bar, slide overview, printing) is finished and tested; `scripts/build.py` inserts it for you. You write only a **short source file containing the slide content and the narration**. You never open or edit the template. Do not rewrite the player: speech in browsers has many platform quirks (autoplay limits on phones, voices that load late, engines that never report completion), and the player already handles them.

## Workflow

Below, `SKILL_DIR` stands for the absolute path of the folder that contains this SKILL.md.

1. **Plan the deck.** One message per slide. For each slide, decide separately what short words go on screen and what full sentences are spoken.
2. **Read `SKILL_DIR/references/layouts.md`.** It has a copy-paste example for every layout. Use only the class and attribute names listed there; invented names do nothing and fail the lint. For an **information-dense business document** (meeting paper, report, approval request, comparison of options), also read `SKILL_DIR/references/dense.md`, which covers dense mode and the business components (conclusion line, titled boxes, comparison table, schedule table, source note, footer).
3. **Write the source, `<name>.slides.html`.** A settings comment at the top, then a list of `<section class="slide">` elements. Do not write `<html>` or `<body>`.
   ```html
   <!--
   title: 経費精算のやり方
   theme: light
   -->
   <section class="slide title"> … </section>
   <section class="slide"> … </section>
   ```
   `title` appears on the start screen. `theme` is a name from the table below; if the user did not choose one, pick the one that suits the content (`light` when nothing stands out) and tell the user which you picked. Write the on-screen text and the narration in the user's language, and add `lang: en` (or another language code) when the deck is not Japanese, so that a voice for that language is used. Business documents can also set `density: dense` and `footer: …`.
4. **Build and check.** Run (use `python` on Windows):
   ```
   python3 SKILL_DIR/scripts/build.py <name>.slides.html --shots <name>-shots
   ```
   This lints the source, assembles `<name>.html`, and checks the rendered deck in a headless browser.
   - Each finding starts with `ERROR` (must be fixed) or `WARNING` (use your judgement) and gives the **source line number** and a **Fix:** line. Apply the fixes to the source and rerun the same command until the last line reads `RESULT: OK`.
   - Never edit the built HTML; the next build overwrites it.
   - The output also lists the number of sentences and the seconds of narration per slide. Check that no slide runs too long.
5. **Look at the screenshots.** `<name>-shots/` holds a PNG of every slide with all elements revealed (`slide-01.png` …) and two phone views (the slide with the most text, with a caption showing). The check only knows whether things fit, so open several images and judge by eye whether any slide is cramped, sparse or hard to read. Fix and rebuild if so.
6. **Report to the user.** Say where the HTML file is, that it opens by double-click, how to operate it (see below), and which theme you chose. Leave the source file next to the HTML for later edits. If you added anything the user did not give you, say exactly what.

### Editing an existing deck

If `<name>.slides.html` sits next to the deck, edit it and continue from step 4. If only the built HTML exists, recover the source first with `python3 SKILL_DIR/scripts/build.py --extract <name>.html` (rebuilding also upgrades the deck to the current player).

- **When adding, removing or reordering slides**, reread the narration of the neighbouring slides. Counts and connectives ("first", "next", "finally", "the three rules") drift out of step, and no check can catch that.
- **To change the theme**, change `theme:` in the source and rebuild. Themes differ in fonts and corner shapes, so look at the screenshots again.

## Themes

| Name | Look | Suits |
|---|---|---|
| `light` | blue on white; the default | anything, when unsure |
| `dark` | dark navy background | screen sharing, technical topics |
| `corporate` | navy and gold, square corners | formal documents for executives or customers |
| `warm` | cream background, serif headings | stories, values, calm reading |
| `forest` | soft green | environment, health, education |
| `sakura` | pale pink, round corners | gentle announcements |
| `mono` | black and white with a yellow highlighter, thick lines | bold, minimal statements |
| `pop` | pink and cyan on cream, rounded type | friendly introductions, children, general audiences |
| `neon` | cyan and pink on black | tech, games |
| `chalk` | blackboard green, textbook typeface | lessons, study groups |

If the user wants to compare, have them open `assets/themes.html`, a gallery of every theme. Adding `?theme=name` to a deck's URL previews another theme without rebuilding.

## How a slide is written

```html
<section class="slide">
  <h2 data-say="まず、特徴は三つです。">3つの特徴</h2>
  <ul>
    <li data-say="一つ目は、ブラウザが自動で読み上げることです。"><strong>自動ナレーション</strong></li>
    <li data-say="二つ目は、話に合わせて要素が現れることです。"><strong>話に合わせて出現</strong></li>
  </ul>
  <p class="voice">補足です。この文は読み上げと字幕だけで、画面には出ません。</p>
</section>
```

That is the whole mechanism:

- An element with **`data-say="narration"`** appears, animated, at the moment that narration is spoken. Narration runs in document order, top to bottom, including `.voice` elements.
- **`<p class="voice">narration</p>`** shows nothing on the slide; it only adds narration and captions.
- An element with neither is visible from the moment the slide appears.
- `data-say` with no value reads the element's own visible text.
- `data-anim="fade | zoom | pop | left | right"` changes how the element enters (the default rises in from below).
- Narration is split at sentence ends (`。` `！` `？` `.` `!` `?`), and each sentence becomes one caption.

All layout classes (cover, section divider, cards, big number, flow, table, quote, figure, …) are in `references/layouts.md`.

## Writing the narration

The narration is what makes the deck feel like a video. Reading the on-screen text aloud just produces "slides being read out", so put **short keywords on screen and full spoken sentences in the narration**.

- Keep each sentence to about 40 full-width characters (about 80 Latin letters). Longer sentences make captions hard to read and sound unnatural; the check rejects captions over 48 full-width characters (Latin letters count as half).
- **Avoid tiny 2–6 character narration fragments.** Do not put a short lead-in like `data-say="この動画では、"` or `data-say="こちらは、"` on a `.kicker` element (leave `.kicker` without `data-say` and start the full sentence on `<h1>`), and do not split list items with a period after the number (`一つ目。…`); write each bullet as one sentence with a comma (`一つ目は、…`, `二つ目は、…`). Tiny fragments make captions flash for less than a second and make neural TTS unstable.
- Use connectives ("first", "next", "in other words"; まず, 次に, つまり) so that slides flow into each other.
- Aim for 10-30 seconds per slide. The number of sentences does not matter, and a section divider can have one. Consider splitting a slide over 45 seconds; always split one over 60.
- **When the speech engine is likely to misread a word, write the narration phonetically and give the correct spelling in `data-caption`.** In Japanese this applies to Latin abbreviations (API, DX, HTML, GPU), in-house terms and proper nouns, kanji compounds or words with ambiguous readings (方, 行った, 左右 → さゆう, 上下 → じょうげ, 話者 → わしゃ / 日本語の声), and long numbers or amounts (1,200円). Short numbers such as 3つ, 11時 or 5人 can be written as they are.
  ```html
  <h2 data-say="エーピーアイの利用料は、月額せんにひゃく円です。"
      data-caption="APIの利用料は、月額1,200円です。">料金</h2>
  ```
  With several sentences, `data-say` and `data-caption` must have the same number of sentences; they are paired one by one.
- Keep symbols (→, 〜, ／, ※, ＝) out of the narration and say them in words (11時〜15時 is spoken as 11時から15時). The check flags them. The on-screen text may keep the symbols.
- A closing summary with, say, five items can use an `ol` on the `end` slide.

## How much goes on a slide - readable on a phone

This section is the standard for ordinary decks (training, how-to, introductions, announcements). Information-dense business documents follow different limits; see `references/dense.md`.

A slide is a fixed 1280×720px canvas that is scaled as a whole to fit the screen, as in PowerPoint; text never reflows. Held upright, a phone shrinks it to about 0.3×, so the rule is **large type, few words**.

- At most a heading plus six lines of body text per slide. Use 3 or 4 bullets of about 20 full-width characters each.
- Leave the type sizes at their defaults (body text 32-34px). Split the slide rather than shrinking the text; anything under 22px fails the check.
- The bottom 100px is reserved for captions, so no content goes there (the default padding keeps it clear, and the check reports anything that strays into it).
- Leave the detail to the narration. It does not need to be on screen to be understood.

## Rules, and why

- **One file, nothing loaded from outside.** Decks are opened by double-click (`file://`), possibly offline. No CDN, web fonts, `fetch`, or external CSS or JavaScript.
- **Local images are embedded automatically.** Write `<img src="path/to/image.png" alt="…">` relative to the `.slides.html` file (or inline SVG / data URI); `build.py` checks that the file exists and embeds it as a base64 data URI so the deck stays a single offline-ready HTML file. See "Figures and images" in `references/layouts.md` for framed screenshots (`.frame`), text + image columns (`.cols.grow`), photo cards, and full-bleed background photos (`<img class="bg" data-bleed ...>`).
- **Never edit `assets/template.html`.** To change the look, pick another theme or put a `style` attribute on an element. For an adjustment used in several places, write a `<style> … </style>` block in the source; it is included as custom CSS (see "Changing colours" in `references/layouts.md`).
- **Narration uses the browser's built-in speech (Web Speech API). Do not generate audio files.** The voice is whichever one the viewer's device has, so its quality varies by device. That trade-off is intentional: the deck stays one small file and needs no service.
- **Never send the narration text to an outside service.** Do not use cloud text-to-speech (vendor TTS APIs, edge-tts, gTTS, and the like). The player follows the same rule: it uses only voices the browser reports as on-device and never the online voices that send text to a server, so on a device with no such voice (some Android phones) the deck plays with captions only. It also opts out of the browser's automatic page translation.
- Only when the user explicitly asks for a better voice, point them to `scripts/add_voice.py`, which generates audio locally with VOICEVOX / AivisSpeech, Kokoro-82M (`--engine kokoro`, via a local Kokoro-FastAPI server or Python `kokoro` package), or Qwen3-TTS (`--engine qwen3`, via `qwen-tts` with PyTorch on Windows, or `mlx-audio` with batch synthesis and `Qwen3-ForcedAligner` on Apple Silicon) and embeds it in the HTML; its usage is at the top of the script. Do not run it or install `kokoro`, `qwen-tts` or `mlx-audio` unasked — if not installed yet, ask the user before setting up a virtual environment (e.g. `.venv` with Python 3.10–3.12, `kokoro>=0.9.4`, `misaki[ja]`, `python -m unidic download` for Kokoro Japanese, or `mlx-audio` + `nagisa` for Qwen3-TTS) and downloading the model. When you generate embedded audio and have a tool that can inspect audio files (`read_file`), listen to several generated clips to check for misreadings, clipped endings or unnatural pauses and self-correct `data-say` / `data-caption` if needed. `build.py` preserves existing embedded audio clips across rebuilds; if you edit the narration, rerun `add_voice.py` after `build.py` to generate audio for the changed sentences.

## Controls to tell the user about

| Action | Computer | Phone |
|---|---|---|
| Play / pause | Space, or click | tap |
| Previous / next slide | ← → | swipe left / right |
| Previous / next sentence (playing) | ↑ ↓ | — |
| Replay current sentence (playing) | R | — |
| Jump to slide | `1`–`9` (or 2 digits) | progress bar |
| Full screen | F | turn the phone sideways |
| Blank screen (blackout) | B (B / Esc / click restores) | — |
| All slides | G (Esc closes) | the grid button at the bottom |
| Transcript | T (Esc closes) | the list button at the bottom |
| Keyboard shortcuts | `?` (Esc closes) | — |
| Captions / sound / speed | C / M / `<` `>` | buttons at the bottom |

- The first play always needs a press of the play button, because browsers do not let a page start sound by itself.
- Where no voice is available, the deck plays at the same pace with captions only.
- Printing (Ctrl+P) gives a PDF with one slide per page; add `?notes=1` to include speaker notes below each slide when printing. You can also export directly from the command line with `build.py deck.slides.html --pdf deck.pdf` (add `--pdf-notes` for speaker notes), export the narration script as Markdown with `--script deck.md`, export timed captions as WebVTT with `--vtt deck.vtt`, auto-rebuild on save with `--watch`, or open the built deck in your browser with `--open`.
- URL parameters for checking: `?still=1#3` (slide 3, static), `?autoplay=1&mute=1` (plays silently by itself), `?rate=1.25` (playback speed: `0.75`, `1`, `1.25`, `1.5`, `2`), `?caps=0` (captions off), `?overview=1` (opens the slide overview), `?transcript=1` (opens the transcript panel), `?notes=1` (adds speaker notes for printing), `?check=1` (shows the check report). `build.py --json`, `check.py --json`, and `add_voice.py --info/--dry-run --json` output machine-readable JSON.

## When the check cannot run

The source lint needs no browser. The rendered check needs Chrome or Edge; if the script says none was found, set the `CHROME` environment variable to the browser's path. If that is not possible, add `--no-render` to lint and assemble only, keep strictly within the content limits above (six lines, about 20 characters per bullet), and tell the user that overflow has not been verified.
