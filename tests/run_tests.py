#!/usr/bin/env python3
"""Regression tests for the html-slides skill. Run them after changing the player or the scripts.

  python3 tests/run_tests.py

What is covered:
  1. Source lint      : a deliberately broken source produces the expected kinds of error.
  2. Documentation    : every example in SKILL.md and references/*.md passes the lint.
  3. Sample decks     : the standard and dense samples build cleanly in every theme.
  4. Round trip       : extracting the source from a built deck and rebuilding gives the same deck.
  5. Rendered check   : overflow that is easy to miss is reported.
  6. PDF              : printing gives one page per slide.
  7. Interaction      : the sample deck is opened in a headless browser and driven with key presses and clicks
                        (play, pause, resume, navigation, auto-advance, overview, captions, speed, play to the
                        end, replay). No sound is available, so this runs in the silent, captions-only mode.
  8. Narration        : a fake speechSynthesis is injected. The voice list arrives late, one utterance never
                        reports its end and one fails; playback must still reach the end, and an online voice
                        must never be used.
  9. Dead engine      : an engine that never starts speaking and only reports "end" for utterances we cancel
                        (the defect found by model checking).
 10. TLA+             : model checking of tests/tla/Player.tla, only when tla2tools.jar is available
                        (set TLA_JAR to its path).

The sample decks and several fixtures are Japanese because the skill is used mostly for Japanese decks.
"""
from contextlib import contextmanager
import base64
import html
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "html-slides"
sys.dont_write_bytecode = True
sys.path.insert(0, str(SKILL / "scripts"))
import build  # noqa: E402
import check  # noqa: E402

results = []


def ok(name, cond, info=""):
    results.append((name, bool(cond), info))


def errors(issues):
    return [i for i in issues if i.get("level", "error") == "error"]


SELFTEST_JS = r"""
<script>
(async function () {
  const R = [];
  const ok = (n, c, info) => R.push({ name: n, pass: !!c, info: info == null ? '' : String(info) });
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const $ = s => document.querySelector(s);
  const all = () => [...document.querySelectorAll('#stage > section.slide')];
  const cur = () => all().findIndex(s => s.classList.contains('active')) + 1;
  const playing = () => $('#player').classList.contains('playing');
  const pend = () => document.querySelectorAll('#stage .slide.active .pending').length;
  const cap = () => $('#caption-text').textContent;
  const key = k => document.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }));
  const N = all().length;
  try {
    ok('start: slide 1, start screen shown, not playing', cur() === 1 && !$('#start').hidden && !playing());
    ok('start: every element is revealed', pend() === 0);
    ok('start: only the current slide is visible', all().filter(s => getComputedStyle(s).visibility === 'visible').length === 1);
    ok('start: controls are labelled', $('#b-grid').getAttribute('aria-label') === 'All slides' && $('#start-silent').textContent.indexOf('captions only') > 0, $('#b-grid').getAttribute('aria-label'));
    ok('dialogs: no stray title tooltip on dialog containers', !$('#overview').title && !$('#script').title && !$('#help').title);
    ok('mute icon: shows muted slash path when muted', $('#i-mute').getAttribute('d').indexOf('13.5 3') >= 0);

    key('ArrowRight'); ok('right arrow while stopped: slide 2, start screen gone, all revealed', cur() === 2 && $('#start').hidden && pend() === 0);
    const barW = i => parseInt(document.querySelectorAll('#bar button i')[i].style.width, 10) || 0;
    ok('progress bar on slide 2 while stopped: slide 1 is 100%, slide 2 is 0% and marked cur', barW(0) === 100 && barW(1) === 0 && document.querySelectorAll('#bar button')[1].classList.contains('cur'));
    key('ArrowLeft'); ok('left arrow while stopped: back to slide 1', cur() === 1 && barW(0) === 0);
    key('End'); ok('End: last slide', cur() === N);
    key('ArrowRight'); ok('right arrow on the last slide: stays', cur() === N);
    key('Home'); ok('Home: first slide', cur() === 1);
    key('3'); ok('digit 3: jumps directly to slide 3', cur() === 3);
    key('1'); ok('digit 1: jumps directly to slide 1', cur() === 1);
    key('ArrowLeft'); ok('left arrow on the first slide: stays', cur() === 1);
    ok('slide counter', $('#count').textContent.replace(/\s/g, '') === '1/' + N, $('#count').textContent);
    ok('time display', /^\d+:\d\d \/ \d+:\d\d$/.test($('#time').textContent.trim()), $('#time').textContent);
    document.querySelectorAll('#bar button')[1].dispatchEvent(new MouseEvent('mouseenter'));
    ok('progress bar tooltip: shows slide label on hover', $('#bar-tip').classList.contains('show') && $('#bar-tip').textContent.indexOf('2 / ' + N) === 0, $('#bar-tip').textContent);
    document.querySelectorAll('#bar button')[1].dispatchEvent(new MouseEvent('mouseleave'));
    ok('progress bar tooltip: hides on leave', !$('#bar-tip').classList.contains('show'));

    $('#b-play').click(); await sleep(100);
    ok('play: playing, narrated elements hidden', playing() && pend() > 0, 'pending=' + pend());
    await sleep(1500);
    ok('playing: a caption is shown', cap().length > 0 && $('#caption').classList.contains('show'), cap());
    ok('playing: the element being narrated is visible', document.querySelectorAll('#stage .slide.active .speaking:not(.pending)').length >= 1);

    const capBefore = cap(), pendBefore = pend();
    $('#b-cc').focus();
    key('k'); ok('K: pauses even when a control button has focus', !playing());
    $('#b-cc').blur();
    await sleep(4000);
    ok('paused: nothing advances', cur() === 1 && pend() === pendBefore && cap() === capBefore);
    key(' '); await sleep(400);
    ok('resume: continues from the same sentence', playing() && cap() === capBefore && pend() === pendBefore, cap());

    key('ArrowRight'); await sleep(100);
    ok('right arrow while playing: slide 2, still playing, elements hidden again', cur() === 2 && playing() && pend() > 0);
    await sleep(1200);
    ok('after navigating: the caption belongs to slide 2', cap().length > 0 && cap() !== capBefore, cap());
    const capS2First = cap();
    key('ArrowDown'); await sleep(400);
    ok('down arrow while playing: advances to the next sentence on the same slide', cur() === 2 && playing() && cap() !== capS2First, cap());
    const capS2Second = cap();
    key('r'); await sleep(400);
    ok('R while playing: replays the current sentence', cur() === 2 && playing() && cap() === capS2Second, cap());
    key('ArrowUp'); await sleep(400);
    ok('up arrow while playing: returns to the previous sentence on the same slide', cur() === 2 && playing() && cap() === capS2First, cap());
    key('4'); await sleep(150);
    ok('digit key: jumps directly to slide 4', cur() === 4 && playing());
    key('0'); await sleep(150);
    ok('0 key: jumps back to slide 1', cur() === 1 && playing());
    key('2'); await sleep(150);
    await sleep(45000);
    ok('auto-advance: moved on to a later slide', cur() > 2 && playing(), 'slide ' + cur());
    ok('auto-advance: no "speaking" highlight left on earlier slides', document.querySelectorAll('#stage .slide:not(.active) .speaking').length === 0);

    key('g');
    ok('G: overview opens and playback pauses', !$('#overview').hidden && !playing());
    ok('overview: one thumbnail per slide', document.querySelectorAll('.ov-item').length === N);
    ok('overview: each thumbnail shows a duration badge', document.querySelectorAll('.ov-dur').length === N);
    ok('overview: exactly one thumbnail marked current', document.querySelectorAll('.ov-item.current').length === 1);
    const c0 = cur(), ovFocus0 = document.activeElement; key('ArrowRight'); key(' ');
    ok('overview open: arrow moves focus, slide and playback stay put', cur() === c0 && !playing() && (c0 === N || document.activeElement !== ovFocus0));
    key('Escape'); await sleep(300);
    ok('Esc: overview closes and playback resumes', $('#overview').hidden && playing());
    key('g'); document.querySelectorAll('.ov-item')[1].click(); await sleep(300);
    ok('thumbnail click: jumps to slide 2 and resumes', cur() === 2 && playing() && $('#overview').hidden);
    ok('overview closed: thumbnails removed', document.querySelectorAll('.ov-item').length === 0);
    $('#count').click();
    ok('slide counter click: opens overview', !$('#overview').hidden && !playing());
    key('ArrowDown');
    ok('overview: ArrowDown moves focus vertically', document.activeElement && document.activeElement.classList.contains('ov-item'));
    $('#overview').dispatchEvent(new MouseEvent('click', { bubbles: true })); await sleep(200);
    ok('overview: clicking backdrop closes overview', $('#overview').hidden && playing());

    key('t');
    ok('T: transcript opens and playback pauses', !$('#script').hidden && !playing());
    const totalLines = document.querySelectorAll('.sc-line').length;
    ok('transcript: lists narration sentences', totalLines >= N);
    const scTs = Array.from(document.querySelectorAll('.sc-slide .sc-ts')).map(e => e.textContent);
    ok('transcript: shows cumulative chapter timestamps', scTs.length === N && scTs[0] === '0:00' && scTs[1] !== '0:00', scTs.join(', '));
    key('/');
    ok('transcript: / focuses search box', document.activeElement === $('#sc-search'));
    $('#sc-search').value = 'スマホ'; $('#sc-search').dispatchEvent(new Event('input'));
    const filteredLines = document.querySelectorAll('.sc-line:not([hidden])').length;
    ok('transcript search: filters sentences', filteredLines > 0 && filteredLines < totalLines, filteredLines + '/' + totalLines);
    ok('transcript search: highlights matched substring with mark.sc-hit', document.querySelectorAll('.sc-line:not([hidden]) mark.sc-hit').length >= filteredLines);
    ok('transcript search: search input has aria-label', !!$('#sc-search').getAttribute('aria-label'));
    ok('transcript search: shows match count', $('#sc-count').textContent === filteredLines + ' / ' + totalLines && $('#sc-empty').hidden);
    $('#sc-search').dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
    ok('transcript search: ArrowDown focuses first matching line', document.activeElement && document.activeElement.classList.contains('sc-line'));
    key('ArrowUp');
    ok('transcript search: ArrowUp from first line returns focus to search', document.activeElement === $('#sc-search'));
    ok('transcript open: start screen is inert and dialog is aria-modal', $('#start').inert === true && $('#script').getAttribute('aria-modal') === 'true');
    $('#sc-search').value = '___no_match___'; $('#sc-search').dispatchEvent(new Event('input'));
    ok('transcript search: shows empty state on 0 matches', !$('#sc-empty').hidden && $('#sc-count').textContent === '0 / ' + totalLines);
    key('Escape'); await sleep(300);
    ok('Esc: transcript closes and playback resumes', $('#script').hidden && playing() && $('#start').inert === false);
    key('t'); $('#sc-search').value = 'スマホ'; $('#sc-search').dispatchEvent(new Event('input'));
    $('#sc-search').dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })); await sleep(300);
    ok('transcript search: Enter jumps to first matching sentence', $('#script').hidden && playing());
    ok('slide counter: aria-label includes current slide number', $('#count').getAttribute('aria-label').indexOf(cur() + ' / ' + N) === 0, $('#count').getAttribute('aria-label'));
    key('t'); $('#sc-backdrop').click(); await sleep(200);
    ok('transcript: clicking backdrop closes transcript', $('#script').hidden && playing());
    key('t'); document.querySelectorAll('.sc-slide')[2].click(); await sleep(300);
    ok('transcript click: jumps to slide 3 and resumes', cur() === 3 && playing() && $('#script').hidden);

    key('?');
    ok('?: shortcuts help opens and playback pauses', !$('#help').hidden && !playing());
    key('Escape'); await sleep(300);
    ok('Esc: shortcuts help closes and playback resumes', $('#help').hidden && playing());
    $('#b-help').click();
    ok('help button: opens shortcuts help and pauses', !$('#help').hidden && !playing());
    key('Escape'); await sleep(300);
    key('b');
    ok('B: blackout opens and pauses playback', !$('#blank').hidden && !playing());
    key('b'); await sleep(300);
    ok('B again: blackout closes and resumes playback', $('#blank').hidden && playing());

    key('c'); ok('C: captions off', !$('#caption').classList.contains('show') && $('#b-cc').getAttribute('aria-pressed') === 'false');
    key('c'); await sleep(50); ok('C: captions on', ($('#caption').classList.contains('show') || cap() === '') && $('#b-cc').getAttribute('aria-pressed') === 'true');
    const r0 = $('#b-rate').textContent; key('>');
    ok('>: speed changes', $('#b-rate').textContent !== r0, $('#b-rate').textContent);
    await sleep(600); ok('after a speed change: still playing', playing() && cap().length > 0);
    key('<'); ok('<: speed restored', $('#b-rate').textContent === r0);

    key(' ');
    key('g'); key('Escape'); await sleep(200);
    ok('overview opened and closed while stopped: stays stopped', !playing());
    key('t');
    const scLines = document.querySelectorAll('.sc-line');
    const targetLine = scLines[scLines.length - 1];
    const targetCap = targetLine.textContent;
    targetLine.click(); await sleep(150);
    ok('transcript line click while paused: jumps, highlights cue, and shows caption',
       $('#script').hidden && !playing() && cur() === N && cap() === targetCap && document.querySelectorAll('#stage .slide.active .speaking').length === 1);
    key(' '); await sleep(100);

    key('End'); await sleep(70000);
    ok('played to the end: stops and shows the start screen', !playing() && !$('#start').hidden && cur() === N, 'slide ' + cur());
    ok('at the end: all revealed, no caption, all progress bars 100%', pend() === 0 && cap() === '' && barW(N - 1) === 100);
    $('#start-play').click(); await sleep(400);
    ok('replay: starts from slide 1', cur() === 1 && playing() && $('#start').hidden);

    key(' '); key('ArrowRight');
    ok('navigating while stopped: all revealed', pend() === 0 && cur() === 2 && !playing());
    key(' '); await sleep(100);
    ok('play after navigating while stopped: starts that slide from the top', playing() && pend() > 0);
    await sleep(800);
    const before = cur();
    key(' '); key(' '); key(' '); await sleep(30000);
    ok('three rapid Space presses: stopped, and stays put', !playing() && cur() === before, 'slide ' + cur());
    key('ArrowRight'); key('ArrowRight'); key('ArrowLeft'); await sleep(2000);
    ok('several moves while stopped: does not start playing by itself', !playing() && pend() === 0);
  } catch (e) { ok('exception during the test', false, e && e.stack || e); }
  const pre = document.createElement('pre'); pre.id = 'selftest'; pre.textContent = JSON.stringify(R); document.body.appendChild(pre);
})();
</script>
"""

# A fake speechSynthesis. The voice list arrives late and mixes online voices with an on-device one.
# The 3rd utterance never reports its end; the 5th fails.
# With window.__ttsDead set, the engine never starts speaking, and cancel() makes it report "end" for that utterance.
TTS_MOCK_JS = r"""
<script>
(function () {
  var log = window.__tts = { spoken: [], voices: [], cancels: 0 };
  var voices = [], listeners = [], current = null, n = 0, deadU = null;
  var all = [
    { name: 'Microsoft Nanami Online (Natural) - Japanese (Japan)', lang: 'ja-JP', localService: false, default: true },
    { name: 'Google Japanese', lang: 'ja-JP', localService: false, default: false },
    { name: 'Microsoft Haruka - Japanese (Japan)', lang: 'ja-JP', localService: true, default: false },
    { name: 'Samantha', lang: 'en-US', localService: true, default: false }
  ];
  var mock = {
    getVoices: function () { return voices.slice(); },
    addEventListener: function (t, f) { listeners.push(f); },
    cancel: function () {
      log.cancels++; if (current) { clearTimeout(current); current = null; }
      if (deadU) { var d = deadU; deadU = null; setTimeout(function () { if (d.onend) d.onend(); }, 10); }
    },
    pause: function () {}, resume: function () {},
    speak: function (u) {
      if (!u.text.trim()) return;
      var k = ++n; log.spoken.push(u.text); log.voices.push(u.voice ? u.voice.name : '(default voice)');
      if (window.__ttsDead) { deadU = u; return; }
      current = setTimeout(function () {
        if (u.onstart) u.onstart();
        current = setTimeout(function () {
          current = null;
          if (k === 3) return;
          if (k === 5) { if (u.onerror) u.onerror({ error: 'synthesis-failed' }); return; }
          if (u.onend) u.onend();
        }, 700);
      }, 60);
    }
  };
  Object.defineProperty(window, 'speechSynthesis', { value: mock, configurable: true });
  window.SpeechSynthesisUtterance = function (t) { this.text = t; };
  setTimeout(function () { voices = all; listeners.forEach(function (f) { f(); }); }, 900);
})();
</script>
"""
TTS_TEST_JS = r"""
<script>
(async function () {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const $ = s => document.querySelector(s);
  const all = () => [...document.querySelectorAll('#stage > section.slide')];
  const cur = () => all().findIndex(s => s.classList.contains('active')) + 1;
  const out = {};
  try {
    let toastSeen = '';
    new MutationObserver(() => { if ($('#toast').textContent) toastSeen = $('#toast').textContent; }).observe($('#toast'), { childList: true, characterData: true, subtree: true });
    $('#start-play').click();                       // start playing before the voice list arrives
    await sleep(3000);
    out.toastEarly = $('#toast').textContent;
    out.mutedIconEarly = $('#b-mute').classList.contains('off');
    await sleep(240000);
    out.ended = !$('#player').classList.contains('playing') && !$('#start').hidden && cur() === all().length;
    out.slide = cur();
    out.toastEnd = $('#toast').textContent; out.toastSeen = toastSeen;
    out.voiceMenu = [...$('#voice').options].map(o => o.value);
    out.log = window.__tts;
  } catch (e) { out.error = String(e && e.stack || e); }
  const pre = document.createElement('pre'); pre.id = 'ttstest'; pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
})();
</script>
"""

BROKEN = """<!--
title: broken source
theme: drak
-->
<section class="slide bullets">
  <h2 data-speak="A heading.">Heading</h2>
  <ul>
    <li data-say="First." data-anim="slide">Item</li>
    <li class="highlight">Item</li>
  </ul>
</section>
<section class="slide">
  <h2>No narration</h2>
  <p class="center" style="font-size:16px">small</p>
  <div class="cols"><div class="card"><p>never closed</div>
</section>
<section class="slide">
  <h2 data-say="One. Two." data-caption="1 and 2.">x</h2>
  <img src="https://example.com/a.png" alt="x">
  <script>alert(1)</script>
</section>
"""
EXPECT = ["unknown-theme", "unknown-class", "unknown-attr", "unknown-anim", "no-narration", "small-text", "unclosed", "caption-mismatch", "external", "script"]
HEAD = "<!--\ntitle: t\ntheme: light\n-->\n"
COVER = '<section class="slide title"><h1 data-say="Hello.">x</h1></section>\n'


def js_errors(stderr):
    return [l for l in stderr.splitlines() if re.search(r"Uncaught|TypeError|ReferenceError|SyntaxError", l)]


def built(tmp, name, source):
    meta, css, slides, issues, lines = build.lint(source)
    deck = tmp / name
    build.assemble(meta, css, slides, deck)
    return deck


def main():
    check.setup_console()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="html-slides-test-"))
    starter = SKILL / "assets" / "starter.slides.html"
    browser = check.find_browser()
    if not browser:
        print("Chrome / Edge was not found, so the tests cannot run.")
        return 2

    # --- 1. source lint ---
    types = {i["type"] for i in errors(build.lint(BROKEN)[3])}
    for t in EXPECT:
        ok("lint: reports %s" % t, t in types)
    meta, css, slides, issues, lines = build.lint(starter.read_text(encoding="utf-8"))
    ok("lint: the sample source has no errors", not errors(issues), issues)
    ok("lint: a source without settings is an error", any(i["type"] == "no-header" for i in build.lint('<section class="slide"><h2 data-say="Hi.">x</h2></section>')[3]))
    good = HEAD + '<style>.mine { color: red; }</style>\n<section class="slide title">\n<h1 data-say>Title</h1>\n<p class="mine">x<br>y</p>\n<ul><li>a<li>b</ul>\n<svg viewBox="0 0 10 10"><rect width="5" height="5"/><text font-size="3">a</text></svg>\n<a href="https://example.com">link</a>\n</section>'
    ok("lint: accepts custom classes, optional end tags, SVG and links", not errors(build.lint(good)[3]), build.lint(good)[3])
    header = HEAD + '<section class="slide title"><header><h1 data-say>Title</h1></header></section>'
    ok("lint: a slide can contain a header element", not errors(build.lint(header)[3]))
    ok("lint: document tags are detected regardless of case",
       any(i["type"] == "whole-page" for i in errors(build.lint(HEAD + "<HTML></HTML>")[3])))
    commented = "<!-- <style>.inactive { color: red }</style> -->"
    narrated = '<section class="slide title"><h1 class="active" data-say="Use <style> tags </style> here">Demo</h1></section>'
    style_source = HEAD + commented + '\n<STYLE title="a > b">.active { color: blue }</STYLE>\n<style>h1 { margin: 0 }</style>\n' + narrated
    _, css_blocks, markup, style_issues, _ = build.lint(style_source)
    ok("styles: extracts active rules in order across tag case and quoted attributes",
       not errors(style_issues) and css_blocks == ".active { color: blue }\nh1 { margin: 0 }", style_issues)
    ok("styles: preserves comments and literal markup inside narration", commented in markup and narrated in markup)
    unclosed = build.lint(HEAD + COVER + "\n<style>h1 { color: blue }")[3]
    ok("styles: reports an unterminated block at its opening line",
       any(i["type"] == "unclosed" and i["line"] == (HEAD + COVER + "\n").count("\n") + 1 for i in errors(unclosed)))
    bom = tmp / "bom.slides.html"
    bom.write_bytes(b"\xef\xbb\xbf" + starter.read_bytes())
    ok("lint: reads a source that starts with a BOM", not errors(build.lint(build.read_source(bom))[3]))
    typo_meta = '<!--\ntitle: t\nthme: dark\n-->\n<section class="slide title"><h1 data-say="Hello.">x</h1></section>'
    typo_issues = build.lint(typo_meta)[3]
    ok("lint: warns on unknown setting typo with suggestion", any(i["type"] == "unknown-setting" and i["level"] == "warn" and "theme" in i["hint"] for i in typo_issues), typo_issues)
    no_title_with_warn = '\n\n<!--\ntheme: light\nthme: dark\n-->\n<section class="slide title"><h1 data-say="Hello.">x</h1></section>'
    ntw_issues = build.lint(no_title_with_warn)[3]
    ok("lint: no-title-setting still errors alongside warnings", any(i["type"] == "no-title-setting" and i["level"] == "error" for i in ntw_issues), ntw_issues)
    ok("lint: unknown-setting reports exact line after leading blanks", any(i["type"] == "unknown-setting" and i["line"] == 5 for i in ntw_issues), ntw_issues)
    empty_lang = '<!--\ntitle: t\nlang:\ndensity:\n-->\n<section class="slide title"><h1 data-say="Hello.">x</h1></section>'
    el_meta, _, _, el_issues, _ = build.lint(empty_lang)
    ok("lint: empty lang/density falls back to defaults", not errors(el_issues) and el_meta["lang"] == "ja" and el_meta["density"] == "normal")
    ext_css = '<!--\ntitle: t\n-->\n<style>@import url("https://example.com/a.css");</style>\n<section class="slide title"><h1 data-say="Hello.">x</h1></section>'
    ok("lint: rejects external URL/@import in custom <style>", any(i["type"] == "external" for i in errors(build.lint(ext_css)[3])))
    nested_fb = built(tmp, "nested-fb.html", '<!--\ntitle: t\n-->\n<section class="slide title"><ul><li><p>OnlyOnce</p></li></ul></section>')
    ok("fallback narration: does not duplicate nested li>p text", check.inspect(nested_fb)["texts"] == ["OnlyOnce"], check.inspect(nested_fb)["texts"])
    bin_file = tmp / "binary.dat"
    bin_file.write_bytes(b"\xff\xfe\x00\x01")
    try:
        check.inspect(bin_file)
        ok("check.inspect: raises CheckError on binary file", False)
    except check.CheckError:
        ok("check.inspect: raises CheckError on binary file", True)
    r_pdf_notes = subprocess.run([sys.executable, str(SKILL / "scripts" / "check.py"), str(nested_fb), "--pdf-notes"], capture_output=True, text=True)
    ok("check.py: rejects --pdf-notes without --pdf", r_pdf_notes.returncode == 2)
    r_bad_spd = subprocess.run([sys.executable, str(SKILL / "scripts" / "add_voice.py"), str(nested_fb), "--speed", "0"], capture_output=True, text=True)
    ok("add_voice.py: rejects --speed 0 on all platforms", r_bad_spd.returncode == 2)
    r_bad_tmp = subprocess.run([sys.executable, str(SKILL / "scripts" / "add_voice.py"), str(nested_fb), "--temperature", "-1"], capture_output=True, text=True)
    ok("add_voice.py: rejects negative --temperature", r_bad_tmp.returncode == 2)
    r_bin_v = subprocess.run([sys.executable, str(SKILL / "scripts" / "add_voice.py"), str(bin_file)], capture_output=True, text=True)
    ok("add_voice.py: handles binary file cleanly without traceback", r_bin_v.returncode == 2 and "Traceback" not in r_bin_v.stderr)
    r_bld_notes = subprocess.run([sys.executable, str(SKILL / "scripts" / "build.py"), str(SKILL / "assets" / "starter.slides.html"), "--pdf-notes"], capture_output=True, text=True)
    ok("build.py: rejects --pdf-notes without --pdf", r_bld_notes.returncode == 2)
    mixed = "本当ですか！？はい。「そうです。」 It works. Yes!"
    ok("sentence splitting matches the player", build.sentences(mixed) == ["本当ですか！？", "はい。", "「そうです。」", "It works.", "Yes!"], build.sentences(mixed))

    # --- 2. documentation examples ---
    bad = []
    for md in (SKILL / "references" / "layouts.md", SKILL / "references" / "dense.md", SKILL / "SKILL.md"):
        for k, b in enumerate(re.findall(r"```html\n(.*?)```", md.read_text(encoding="utf-8"), re.S)):
            b = b.replace("…", "")
            if "<section" in b and re.search(r"<section[^>]*>\s*</section>", b):
                continue  # an outline, not a real slide
            if b.lstrip().startswith("<!--") and "<section" not in b:
                continue  # settings only
            if not b.lstrip().startswith("<!--"):
                b = HEAD + (b if "<section" in b else '<section class="slide title">\n<h1 data-say="Hello.">x</h1>\n' + b + "</section>")
            bad += ["%s #%d %s" % (md.name, k, i["type"]) for i in errors(build.lint(b)[3])]
    ok("docs: every example passes the lint", not bad, bad)

    # --- 3. sample decks ---
    deck = tmp / "starter.html"
    build.assemble(meta, css, slides, deck)
    rep = check.inspect(deck)
    ok("sample: no errors or warnings in the rendered check", not rep["issues"], rep["issues"])
    pdf_plain = tmp / "starter.pdf"
    check.export_pdf(rep, pdf_plain, notes=False)
    ok("pdf export: writes a valid PDF file", pdf_plain.is_file() and pdf_plain.read_bytes().startswith(b"%PDF-") and pdf_plain.stat().st_size > 1000)
    pdf_notes = tmp / "starter-notes.pdf"
    check.export_pdf(rep, pdf_notes, notes=True)
    ok("pdf export with notes: writes a larger PDF file", pdf_notes.is_file() and pdf_notes.read_bytes().startswith(b"%PDF-") and pdf_notes.stat().st_size > pdf_plain.stat().st_size)
    md_script = tmp / "starter-script.md"
    check.export_script(rep, md_script)
    md_text = md_script.read_text(encoding="utf-8")
    ok("script export: writes Markdown headings and narration lines", md_text.startswith("# ") and md_text.count("\n## ") == rep["slides"] and "- " in md_text)
    vtt_file = tmp / "starter.vtt"
    check.export_vtt(rep, vtt_file)
    vtt_text = vtt_file.read_text(encoding="utf-8")
    ok("vtt export: writes valid WebVTT with timestamps", vtt_text.startswith("WEBVTT\n\n1\n00:") and " --> " in vtt_text)

    # --- local image embedding & layouts ---
    img_dir = tmp / "img-deck"
    img_dir.mkdir()
    tiny_png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC")
    (img_dir / "pic.png").write_bytes(tiny_png)
    missing_src = HEAD + '<section class="slide title"><h1 data-say="Hi.">x</h1><img src="nope.png" alt="missing"></section>'
    ok("images: lint reports missing local image", any(i["type"] == "missing-image" for i in errors(build.lint(missing_src, base_dir=img_dir)[3])))
    img_src = (
        '<!--\ntitle: Images\ntheme: light\n-->\n'
        '<section class="slide title"><img class="bg" data-bleed src="pic.png" alt=""><h1 data-say="Cover.">Cover</h1></section>\n'
        '<section class="slide"><h2 data-say="Shot.">Shot</h2><figure class="grow"><img class="frame" src="pic.png" alt="s"><figcaption>Cap</figcaption></figure></section>\n'
        '<section class="slide"><h2 data-say="Cols.">Cols</h2><div class="cols grow"><ul><li data-say="One.">One</li></ul><figure><img class="cover" src="pic.png" alt="c"></figure></div></section>\n'
        '<section class="slide"><h2 data-say="Cards.">Cards</h2><div class="cols"><div class="card" data-say="A."><img src="pic.png" alt="a"><h3>A</h3><p>Desc</p></div></div></section>\n'
    )
    im_meta, im_css, im_slides, im_issues, _ = build.lint(img_src, base_dir=img_dir)
    ok("images: lint is clean for all image layouts", not im_issues, im_issues)
    im_html = img_dir / "img.html"
    build.assemble(im_meta, im_css, im_slides, im_html, base_dir=img_dir, inline_images=True)
    im_text = im_html.read_text(encoding="utf-8")
    ok("images: local PNGs are embedded as data URIs", im_text.count("data:image/png;base64,") == 4 and 'src="pic.png"' not in im_text)
    im_rep = check.inspect(im_html)
    ok("images: rendered check is clean for all image layouts", not im_rep["issues"], im_rep["issues"])
    im_ext = img_dir / "img-ext.html"
    build.assemble(im_meta, im_css, im_slides, im_ext, base_dir=img_dir, inline_images=False)
    ok("images: --no-inline-images keeps relative src", 'src="pic.png"' in im_ext.read_text(encoding="utf-8"))
    broken_src = HEAD + '<section class="slide title"><h1 data-say="Hi.">x</h1><img src="data:image/png;base64,AAAA" alt="bad"></section>'
    ok("images: rendered check catches broken images", any(i["type"] == "broken-image" for i in check.inspect(built(tmp, "broken-img.html", broken_src))["issues"]))
    edge_src = (
        '<!--\ntitle: Edge\ntheme: light\n-->\n'
        '<section class="slide title"><img class="bg" src="pic.png" alt=""><h1 data-say="Hi.">Hi</h1>'
        '<!-- <img src="pic.png" alt="comment"> -->'
        '<img alt="A > B" src="pic.png"><img src=pic.png alt="unquoted"></section>\n'
    )
    em_meta, em_css, em_slides, em_issues, _ = build.lint(edge_src, base_dir=img_dir)
    ok("images: edge-case lint is clean", not em_issues, em_issues)
    em_html = img_dir / "edge.html"
    build.assemble(em_meta, em_css, em_slides, em_html, base_dir=img_dir, inline_images=True)
    em_text = em_html.read_text(encoding="utf-8")
    ok("images: skips HTML comments and embeds alt-with-> and unquoted src", em_text.count("data:image/png;base64,") == 3 and '<!-- <img src="pic.png"' in em_text)
    ok("images: img.bg works without data-bleed", not check.inspect(em_html)["issues"])
    file_url_src = HEAD + '<section class="slide title"><h1 data-say="Hi.">x</h1><img src="file:///tmp/pic.png" alt="f"></section>'
    ok("images: lint rejects file:// URLs", any(i["type"] == "external" for i in errors(build.lint(file_url_src, base_dir=img_dir)[3])))
    (img_dir / "50%20.png").write_bytes(tiny_png)
    (img_dir / "my pic.png").write_bytes(tiny_png)
    attr_src = (
        '<!--\ntitle: Attr\ntheme: light\nfooter: Confidential\n-->\n'
        '<section class="slide title"><img class="bg" src="pic.png" alt=""><h1 data-say="Hi.">Hi</h1></section>\n'
        '<section class="slide"><img class="bg" src="pic.png" alt=""><h2 data-say="Slide 2.">Slide 2</h2>'
        '<img data-caption=\'Use src="pic.png" here\' data-say="Demo." src="50%20.png" alt="d">'
        '<img src="my%20pic.png" alt="s"></section>\n'
    )
    am_meta, am_css, am_slides, am_issues, _ = build.lint(attr_src, base_dir=img_dir)
    ok("images: attr-token & percent/space paths pass lint", not am_issues, am_issues)
    am_html = img_dir / "attr.html"
    build.assemble(am_meta, am_css, am_slides, am_html, base_dir=img_dir, inline_images=True)
    am_text = am_html.read_text(encoding="utf-8")
    ok("images: never rewrites src= inside another attribute value", 'data-caption=\'Use src="pic.png" here\'' in am_text and am_text.count("data:image/png;base64,") == 4)
    ok("images: img.bg with footer passes rendered check", not check.inspect(am_html)["issues"])
    watch_src = img_dir / "watch.slides.html"
    watch_src.write_text(attr_src, encoding="utf-8")
    sig1 = build._watch_sig(watch_src)
    (img_dir / "pic.png").write_bytes(tiny_png + b"\x00")
    sig2 = build._watch_sig(watch_src)
    ok("images: --watch detects changes to referenced local images", sig1 != sig2)
    for theme in build.THEMES:
        d = tmp / ("theme-%s.html" % theme)
        build.assemble(dict(meta, theme=theme), css, slides, d)
        r = check.inspect(d)
        ok("theme %s: sample deck is clean" % theme, not r["issues"], r["issues"])

    dsrc = (SKILL / "assets" / "starter-dense.slides.html").read_text(encoding="utf-8")
    dmeta, dcss, dslides, dissues, dlines = build.lint(dsrc)
    ok("dense sample: lint is clean", not dissues, dissues)
    ddeck = tmp / "dense.html"
    build.assemble(dmeta, dcss, dslides, ddeck)
    drep = check.inspect(ddeck)
    ok("dense sample: rendered check is clean", not drep["issues"], drep["issues"])
    ok("dense sample: every slide except the cover and closing slide is dense", [x.get("dense") for x in drep["stats"]] == [False, True, True, True, True, False], [x.get("dense") for x in drep["stats"]])
    dt = ddeck.read_text(encoding="utf-8")
    ok("dense sample: settings reach the built HTML", 'data-density="dense"' in dt and "data-footer=" in dt)
    for theme in build.THEMES:
        d = tmp / ("dense-%s.html" % theme)
        build.assemble(dict(dmeta, theme=theme), dcss, dslides, d)
        r = check.inspect(d)
        ok("theme %s: dense sample is clean" % theme, not r["issues"], r["issues"])
    small = dsrc.replace('<p class="source">', '<p class="source" style="font-size:12px">', 1)
    ok("dense: text under 14px is an error", any(i["type"] == "small-text" for i in check.inspect(built(tmp, "dense-small.html", small))["issues"]) or any(i["type"] == "small-text" for i in build.lint(small)[3]))

    pair = ('<!--\ntitle: t\ntheme: light\ndensity: dense\n-->\n<section class="slide title"><h1 data-say="エーピーアイです。せんにひゃく円です。" data-caption="APIです。1,200円です。">x</h1></section>\n'
            '<section class="slide"><h2 data-say>Table</h2><table><tbody><tr><th>a</th><td><span class="tag ok">done</span></td><td class="ok">○<small>note</small></td></tr></tbody></table></section>')
    ok("captions: several sentences are accepted when data-say and data-caption match in number", not errors(build.lint(pair)[3]), build.lint(pair)[3])
    pr = check.inspect(built(tmp, "pair.html", pair))
    ok("captions: sentences are paired one by one", pr["texts"][:2] == ["エーピーアイです。", "せんにひゃく円です。"], pr["texts"][:3])
    ok("dense: labels and remarks inside a table are not too small", not [i for i in pr["issues"] if i["type"] == "small-text"], pr["issues"])

    # Capture every view before replacing a previous export.
    gallery = tmp / "screenshots"
    gallery.mkdir()
    wrapper = gallery / "_mobile-portrait.html"
    wrapper.write_text("existing user file", encoding="utf-8")
    obsolete = gallery / "slide-100.png"
    obsolete.touch()
    check.shots(pr, gallery)
    expected = {"slide-01.png", "slide-02.png", "mobile-portrait.png", "mobile-landscape.png"}
    images = {p.name: p.read_bytes() for p in gallery.glob("*.png")}
    ok("shots: exports every view and removes obsolete three-digit slides",
       set(images) == expected and all(data.startswith(b"\x89PNG\r\n\x1a\n") for data in images.values()))
    ok("shots: keeps existing files named like phone wrappers",
       wrapper.exists() and wrapper.read_text(encoding="utf-8") == "existing user file")

    def missing_landscape(browser, args):
        path = pathlib.Path(next(arg.split("=", 1)[1] for arg in args if arg.startswith("--screenshot=")))
        if path.name != "mobile-landscape.png":
            path.write_bytes(b"replacement")
        return subprocess.CompletedProcess(args, 0, stderr="")

    with patch.object(check, "run", missing_landscape):
        try:
            check.shots(pr, gallery)
        except check.CheckError as e:
            ok("shots: reports a missing phone capture", "mobile-landscape.png" in str(e))
        else:
            ok("shots: reports a missing phone capture", False)
    ok("shots: a capture failure preserves previous images and removes temporary files",
       set(p.name for p in gallery.iterdir()) == expected | {wrapper.name}
       and all((gallery / name).read_bytes() == data for name, data in images.items()))

    # --- 4. round trip ---
    for mode, source, flags in (("build", starter, ["--no-render"]), ("extract", deck, ["--extract"])):
        original = source.read_bytes()
        input_path = tmp / ("input-" + mode + ".html")
        input_path.write_bytes(original)
        alias = tmp / ("alias-" + mode + ".html")
        os.link(input_path, alias)
        for output in (input_path, alias):
            result = subprocess.run([sys.executable, build.__file__, *flags, str(input_path), "-o", str(output)],
                                    capture_output=True, text=True)
            ok("%s: refuses to overwrite input via %s" % (mode, output.name),
               result.returncode == 2 and "same as the source" in result.stdout and input_path.read_bytes() == original)
    competing_deck = tmp / "competing.html"
    competing_deck.write_bytes(deck.read_bytes())
    competing_source = tmp / "competing.slides.html"
    stage = build.staged_html

    @contextmanager
    def create_source_before_publish(destination, content):
        with stage(destination, content) as staged:
            destination.write_text("saved by another writer", encoding="utf-8")
            yield staged

    with patch.object(build, "staged_html", create_source_before_publish), \
         patch.object(sys, "argv", ["build.py", "--extract", str(competing_deck)]):
        try:
            build.main()
        except SystemExit as e:
            ok("extract: preserves a source created during default extraction",
               e.code == 2 and competing_source.read_text(encoding="utf-8") == "saved by another writer")
        else:
            ok("extract: preserves a source created during default extraction", False)

    with patch.object(sys, "argv", ["build.py", "--extract", str(competing_deck), "-o", str(competing_source)]):
        ok("extract: explicit output still permits overwriting",
           build.main() == 0 and build.lint(competing_source.read_text(encoding="utf-8"))[2] == slides)

    src2 = tmp / "round.slides.html"
    build.extract(deck, src2)
    m2 = build.lint(src2.read_text(encoding="utf-8"))
    ok("round trip: the extracted source gives the same slides and settings", m2[2] == slides and m2[0] == meta)
    dsrc2 = tmp / "dense-round.slides.html"
    build.extract(ddeck, dsrc2)
    dm2 = build.lint(dsrc2.read_text(encoding="utf-8"))
    ok("round trip: the dense sample keeps its settings and slides", dm2[0] == dmeta and dm2[2] == dslides, (dm2[0], dmeta))

    edited = tmp / "edited.html"
    markup = ddeck.read_text(encoding="utf-8")
    root = "<HTML data-footer='Sales &amp; Ops' data-density=dense DATA-THEME='dark' lang='en'>"
    markup = re.sub(r"<html [^>]+>", root, markup, count=1)
    markup = re.sub(r"<title>.*?</title>", '<TITLE id="name">A &amp; B</TITLE>', markup, count=1)
    edited.write_text(markup, encoding="utf-8")
    recovered = tmp / "nested" / "edited.slides.html"
    result = subprocess.run([sys.executable, build.__file__, "--extract", str(edited), "-o", str(recovered)],
                            capture_output=True, text=True)
    ok("extract: creates the destination directory", result.returncode == 0 and recovered.is_file(), result.stderr)
    if recovered.is_file():
        recovered_meta, _, recovered_slides, _, _ = build.lint(recovered.read_text(encoding="utf-8"))
        ok("extract: preserves settings across equivalent HTML serialization",
           recovered_meta == dict(dmeta, title="A & B", footer="Sales & Ops", theme="dark", lang="en")
           and recovered_slides == dslides, recovered_meta)
    edited.write_text(markup.replace('<TITLE id="name">A &amp; B</TITLE>', ''), encoding="utf-8")
    result = subprocess.run([sys.executable, build.__file__, "--extract", str(edited)],
                            capture_output=True, text=True)
    ok("extract: reports a missing title without writing a source",
       result.returncode == 2 and "no document title" in result.stdout and not (tmp / "edited.slides.html").exists())

    # --- 5. overflow that is easy to miss ---
    cases = (("a long URL that cannot wrap", '<section class="slide"><h2 data-say="Next.">https://example.com/very/long/path/that/cannot/wrap/anywhere/at/all/because/it/has/no/spaces/in/it/whatsoever</h2></section>'),
             ("text spilling out of a box that is too short", '<section class="slide"><h2 data-say="Next.">Heading</h2><div class="cols" style="height:120px"><div class="card"><p>とても長い文章がカードの中に入っていて、高さが足りないので下にあふれてしまう例です。さらに続けて書きます。まだ続きます。</p></div><div class="card"><p>short</p></div></div><p>next element</p></section>'))
    for name, body in cases:
        ok("rendered check: reports %s" % name, any(i["type"] == "overflow" for i in check.inspect(built(tmp, "over.html", HEAD + COVER + body))["issues"]))

    # --- 6. PDF ---
    pdf = tmp / "out.pdf"
    check.run(browser, ["--no-pdf-header-footer", "--print-to-pdf=" + str(pdf), deck.as_uri()])
    pages = len(re.findall(rb"/Type\s*/Page[^s]", pdf.read_bytes())) if pdf.exists() else 0
    ok("PDF: one page per slide", pages == rep["slides"], "pages=%d slides=%d" % (pages, rep["slides"]))

    # --- 7. interaction ---
    st = tmp / "selftest.html"
    st.write_text(deck.read_text(encoding="utf-8").replace("</body>", SELFTEST_JS + "</body>"), encoding="utf-8")
    r = check.run(browser, ["--enable-logging=stderr", "--window-size=1280,720", "--virtual-time-budget=400000", "--dump-dom", st.as_uri() + "?mute=1"], timeout=240)
    m = re.search(r'<pre id="selftest">(.*?)</pre>', r.stdout, re.S)
    ok("interaction: the test ran to the end", bool(m))
    if m:
        for x in json.loads(html.unescape(m.group(1))):
            ok("interaction: " + x["name"], x["pass"], x["info"])
    ok("interaction: no JavaScript errors", not js_errors(r.stderr), js_errors(r.stderr)[:3])

    en = HEAD.replace("-->", "lang: en\n-->") + '<section class="slide title"><h1 data-say="This is a short English deck.">English</h1></section>\n<section class="slide"><h2 data-say="It has two slides.">Two</h2></section>'
    r = check.run(browser, ["--window-size=1280,720", "--virtual-time-budget=3000", "--dump-dom", built(tmp, "en.html", en).as_uri()])
    ok("UI text: labels, start screen and slide count are filled in", 'aria-label="All slides"' in r.stdout and "Play without sound" in r.stdout and "2 slides" in r.stdout)
    rn = check.run(browser, ["--window-size=1280,720", "--virtual-time-budget=3000", "--dump-dom", (tmp / "en.html").as_uri() + "?notes=1"])
    ok("print notes: ?notes=1 injects speaker notes blocks for each slide", rn.stdout.count('class="print-notes"') == 2 and "This is a short English deck." in rn.stdout)

    # --- 8. narration with a fake speech engine ---
    mocked = deck.read_text(encoding="utf-8").replace('<div id="player">', TTS_MOCK_JS + '<div id="player">', 1).replace("</body>", TTS_TEST_JS + "</body>")
    tt = tmp / "ttstest.html"
    tt.write_text(mocked, encoding="utf-8")
    r = check.run(browser, ["--enable-logging=stderr", "--window-size=1280,720", "--virtual-time-budget=600000", "--dump-dom", tt.as_uri()], timeout=240)
    m = re.search(r'<pre id="ttstest">(.*?)</pre>', r.stdout, re.S)
    ok("narration: the test ran to the end", bool(m))
    if m:
        o = json.loads(html.unescape(m.group(1)))
        log = o.get("log") or {"spoken": [], "voices": []}
        total = len(rep["texts"])
        ok("narration: no exception", "error" not in o, o.get("error"))
        ok("narration: playing before the voice list arrives is not treated as 'no voice'", not o.get("toastEarly") and not o.get("mutedIconEarly"), o.get("toastEarly"))
        ok("narration: only the on-device voice was used (never an online or default voice)", log["voices"] and all(v == "Microsoft Haruka - Japanese (Japan)" for v in log["voices"]), sorted(set(log["voices"])))
        ok("narration: online voices are not offered in the voice menu", all("Online" not in v and "Google" not in v for v in o.get("voiceMenu", [])), o.get("voiceMenu"))
        ok("narration: reaches the end even when an utterance never reports its end", o.get("ended"), "slide %s" % o.get("slide"))
        ok("narration: later sentences are still spoken after one failure", len(log["spoken"]) >= total - 3, "spoke %d of %d sentences" % (len(log["spoken"]), total))
        ok("narration: one failure does not switch to captions only", not o.get("toastEnd"), o.get("toastEnd"))
        ok("narration: no sentence is spoken twice", len(log["spoken"]) == len(set(log["spoken"])), [x for x in log["spoken"] if log["spoken"].count(x) > 1][:3])
    ok("narration: no JavaScript errors", not js_errors(r.stderr), js_errors(r.stderr)[:3])

    # --- 9. an engine that never starts speaking (reproduces the defect found by model checking) ---
    td = tmp / "ttsdead.html"
    td.write_text(mocked.replace('<div id="player">', '<div id="player">', 1).replace(TTS_MOCK_JS, "<script>window.__ttsDead = true;</script>" + TTS_MOCK_JS, 1), encoding="utf-8")
    r = check.run(browser, ["--enable-logging=stderr", "--window-size=1280,720", "--virtual-time-budget=900000", "--dump-dom", td.as_uri()], timeout=240)
    m = re.search(r'<pre id="ttstest">(.*?)</pre>', r.stdout, re.S)
    ok("dead engine: the test ran to the end", bool(m))
    if m:
        o = json.loads(html.unescape(m.group(1)))
        log = o.get("log") or {"spoken": []}
        ok("dead engine: reaches the last slide", o.get("ended"), "slide %s" % o.get("slide"))
        ok("dead engine: after two failed sentences it stops trying and plays captions only", len(log["spoken"]) == 2, "tried to speak %d times" % len(log["spoken"]))
        ok("dead engine: tells the viewer it switched to captions only", "captions only" in (o.get("toastSeen") or ""), o.get("toastSeen"))

    # --- 10. TLA+ model checking (only when tla2tools.jar is available) ---
    jar = os.environ.get("TLA_JAR") or str(ROOT / "tests" / "tla" / "tla2tools.jar")
    if os.path.exists(jar):
        env = dict(os.environ, TLA_JAR=jar, MAXUSER=os.environ.get("MAXUSER", "2"))
        tr = subprocess.run(["sh", str(ROOT / "tests" / "tla" / "run.sh")], capture_output=True, text=True, env=env, timeout=900)
        ok("TLA+: the model of the current code has no violations", tr.returncode == 0, tr.stdout[-600:])
        tb = subprocess.run(["sh", str(ROOT / "tests" / "tla" / "run.sh"), "before"], capture_output=True, text=True, env=dict(env, MAXUSER="1"), timeout=900)
        ok("TLA+: the model of the code before the fix shows the defect", tb.returncode == 1 and "NoError is violated" in tb.stdout, tb.stdout[-300:])
    else:
        print("(TLA+ model checking skipped: set TLA_JAR to the path of tla2tools.jar to run it)")

    # --- 11. add_voice Kokoro helpers ---
    import http.server
    import threading
    import add_voice

    ok("add_voice: local_url allows 127.0.0.1", add_voice.local_url("http://127.0.0.1:8880/") == "http://127.0.0.1:8880")
    try:
        add_voice.local_url("https://example.com:8880")
        ok("add_voice: local_url rejects remote host", False, "did not raise")
    except SystemExit:
        ok("add_voice: local_url rejects remote host", True)
    ok("add_voice: kokoro_lang_code maps ja/en/gb", (add_voice.kokoro_lang_code("jf_alpha"), add_voice.kokoro_lang_code("af_heart"), add_voice.kokoro_lang_code("bm_george")) == ("j", "a", "b"))
    ok("add_voice: qwen3_lang_code maps japanese/english/korean/chinese", (add_voice.qwen3_lang_code("Ono_Anna"), add_voice.qwen3_lang_code("Ryan"), add_voice.qwen3_lang_code("Sohee"), add_voice.qwen3_lang_code("Vivian")) == ("japanese", "english", "korean", "chinese"))
    wav = add_voice.pcm_to_wav([0.0, 0.5, -0.5], 24000)
    ok("add_voice: pcm_to_wav produces valid RIFF/WAVE header", wav[:4] == b"RIFF" and wav[8:12] == b"WAVE" and len(wav) == 44 + 6)
    ok("add_voice: wav_duration measures WAV length in seconds", add_voice.wav_duration(add_voice.pcm_to_wav([0.0] * 12000, 24000)) == 0.5)
    sr_t = 24000
    f_t = int(sr_t * 0.02)
    noisy = [0.0] * (30 * f_t) + [0.3] * (5 * f_t) + [0.0] * (40 * f_t) + [0.3] * (5 * f_t) + [0.0] * (30 * f_t)
    cleaned_t = add_voice.clean_speech(noisy, sr_t)
    ok("add_voice: clean_speech trims outer silence and shortens long pauses", len(cleaned_t) < len(noisy) // 2, (len(noisy), len(cleaned_t)))
    ok("add_voice: _prep_qwen3_text normalizes trailing commas and terminal punctuation", add_voice._prep_qwen3_text("テストです、") == "テストです。")
    ok("add_voice: _prep_qwen3_text normalizes numbers, decimals and symbols", add_voice._prep_qwen3_text("費用は4,800万円、平均二・三日、評価は◎") == "費用は四千八百万円、平均二てん三にち、評価はにじゅうまる。")
    ok("add_voice: _prep_qwen3_text converts 5+ digit numbers to 万/億 and % to パーセント", add_voice._prep_qwen3_text("30,000円以上、使用率70%に達し") in ("三万円以上、使用率70パーセントにたっし。", "三万円以上、使用率70パーセントに達し。"))
    for phrase, spoken in (
        ("受付番号は012345です。", "受付番号はゼロ、いち、に、さん、よん、ごです。"),
        ("型番AB12345、版はv1.2.3です。", "型番AB12345、版はv1.2.3です。"),
        ("更新日は2026.11.18です。", "更新日は2026.11.18です。"),
        ("資料名はProject Alpha、合計は123456円です。", "資料名はProject Alpha、合計は十二万三千四百五十六円です。"),
        ("3,000円未満の交通費と初年度1,680万円の稟議、見積の提出。", "三千円みまんの交通費としょねんど千六百八十万円のりんぎ、みつもりの提出。"),
        ("主なリスクと持ち主なのに、見積書と見積もり。", "おもなリスクと持ち主なのに、みつもりしょと見積もり。"),
        ("利用率は2.3%です。", "利用率は2てんさんパーセントです。"),
        ("０．０５％", "ゼロてんゼロごパーセント。"),
        ("気温は−5℃です。", "気温はマイナス5度です。"),
        ("前月比は－0.5％です。", "前月比はマイナスゼロてんごパーセントです。"),
        ("-5℃", "マイナス5度。"),
        ("範囲は5度-10度です。", "範囲は5度-10度です。"),
        ("誤差は±2％です。", "誤差はプラスマイナス2パーセントです。"),
        ("前月比は＋0.5%です。", "前月比はプラスゼロてんごパーセントです。"),
        ("型番はAB-5、日付は2026-11-18です。", "型番はAB-5、日付は2026-11-18です。"),
        ("平均1.010日です。", "平均1てんゼロいちゼロにちです。"),
        ("納期は二、三日です。", "納期は二、三日です。"),
    ):
        ok("qwen3: Japanese number and spacing rules for " + phrase, add_voice._prep_qwen3_text(phrase) == spoken)
    for lang, phrase in (("chinese", "增长20%，温度为5℃。"), ("english", "A × B"), ("korean", "성장률 20%")):
        ok("qwen3: preserves %s narration" % lang, add_voice._prep_qwen3_text(phrase, lang) == phrase)
    for end, onset in ((1000, 1020), (1000, 1003), (1000, 1000), (1000, 980), (1000, 1500)):
        cut = add_voice._min_energy_cut([0.1] * 2000, 1000, end / 1000, onset / 1000)
        ok("qwen3: keeps cut between aligned boundaries %d and %d" % (end, onset),
           min(end, onset) <= cut <= max(end, onset), cut)
    _, _, _, short_issues, _ = build.lint('<!--\ntitle: T\ntheme: light\n-->\n<section class="slide title"><p class="kicker" data-say="こちらは、">K</p><h1 data-say="タイトルです。">T</h1></section>')
    ok("lint: warns on short narration fragment on .kicker", any(i["type"] == "short-sentence" for i in short_issues), short_issues)
    _, _, _, sym_issues, _ = build.lint('<!--\ntitle: T\ntheme: light\n-->\n<section class="slide title"><h1 data-say="評価は◎です。">T</h1></section>')
    ok("lint: warns on rating symbol in data-say", any(i["type"] == "say-symbol" for i in sym_issues), sym_issues)
    v_tmp = tmp / "voice_preserve.html"
    build.assemble({"title": "T", "theme": "light", "lang": "ja", "density": "normal", "footer": None}, "", '<section class="slide title"><h1 data-say="テストです。">T</h1></section>', v_tmp)
    v_tmp.write_text(v_tmp.read_text(encoding="utf-8").replace(build.ENGINE_MARKER, '<!-- VOICE:START -->\n<script type="application/json" id="voice-data">{"clips":{"テストです。":"data:audio/wav;base64,AA=="}}</script>\n<!-- VOICE:END -->\n' + build.ENGINE_MARKER, 1), encoding="utf-8")
    build.assemble({"title": "T", "theme": "dark", "lang": "ja", "density": "normal", "footer": None}, "", '<section class="slide title"><h1 data-say="テストです。">T</h1></section>', v_tmp)
    ok("build: assemble preserves VOICE:START block across rebuilds", "<!-- VOICE:START -->" in v_tmp.read_text(encoding="utf-8"))

    language_deck = tmp / "voice-language.html"
    with patch.object(add_voice.platform, "system", return_value="Darwin"), \
         patch.object(sys, "argv", ["add_voice.py", str(language_deck), "--engine", "qwen3", "--speaker", "Ryan"]), \
         patch.object(add_voice, "qwen3_available", return_value=True), \
         patch.object(add_voice, "compress", return_value=(wav, "audio/wav")), \
         patch.object(add_voice, "qwen3_batch_synth", return_value={"Hello.": wav}) as generate:
        for tag, expected_lang, expected_calls in (("en-US", "english", 1), ("fr-CA", "french", 2), ("fr", "french", 2)):
            build.assemble(dict(meta, lang=tag), "", COVER, language_deck)
            status = add_voice.main()
            ok("qwen3: uses deck language and caches clips for %s" % tag,
               status == 0 and generate.call_count == expected_calls and generate.call_args.kwargs["lang"] == expected_lang)
        build.assemble(dict(meta, lang="fi"), "", COVER, language_deck)
        original = language_deck.read_bytes()
        ok("qwen3: reports an unsupported deck language before synthesis",
           add_voice.main() == 2 and generate.call_count == 2 and language_deck.read_bytes() == original)

    trim_deck = tmp / "reviewed.html"
    build.assemble(meta, "", COVER, trim_deck)
    original_markup = trim_deck.read_text(encoding="utf-8")
    def wav_uri(samples):
        return "data:audio/wav;base64," + base64.b64encode(add_voice.pcm_to_wav(samples, 1000)).decode("ascii")

    samples = [0.0, 0.1, 0.2, 0.3] * 100
    uri = wav_uri(samples)
    voice_data = {"voice": "test", "speed": 1, "clips": {"Hello.": uri, "Other.": uri}}
    add_voice.save_voice_data(trim_deck, original_markup, voice_data)
    before = trim_deck.read_bytes()
    before_trim = trim_deck.read_text(encoding="utf-8")
    for sentence, end in (("missing", "0.2"), ("Hello.", "nan"), ("Hello.", "0.5"), ("Hello.", "0")):
        with patch.object(sys, "argv", ["add_voice.py", str(trim_deck), "--trim-clip", sentence, end]):
            ok("trim: rejects %s %s without changing the deck" % (sentence, end),
               add_voice.main() == 2 and trim_deck.read_bytes() == before)
    with patch.object(sys, "argv", ["add_voice.py", str(trim_deck), "--trim-clip", "Hello.", "0.2"]):
        ok("trim: edits an embedded clip without a speech engine", add_voice.main() == 0)
    reviewed = trim_deck.read_text(encoding="utf-8")
    actual = json.loads(re.search(r'id="voice-data">(.*?)</script>', reviewed, re.S)[1])
    voice_data["clips"]["Hello."] = wav_uri(samples[:200])
    ok("trim: preserves exact PCM frames, all other clips and cache settings", actual == voice_data)
    ok("trim: preserves the player and slides", add_voice.BLOCK.sub("", reviewed) == original_markup)

    # Fail after the first bytes are written, as a full filesystem can do.
    protected = tmp / "interrupted"
    protected.mkdir()
    target = protected / "deck.html"
    target.write_bytes(trim_deck.read_bytes())
    existing = target.read_bytes()
    def short_write(path, content, **kwargs):
        path.write_bytes(content[:16].encode("utf-8"))
        raise OSError("simulated short write")
    for operation, publish in (("build", lambda: build.assemble(meta, "", COVER, target)),
                               ("extract", lambda: build.extract(trim_deck, target))):
        for present in (True, False):
            if present:
                target.write_bytes(existing)
            else:
                target.unlink()
            with patch.object(pathlib.Path, "write_text", short_write):
                try:
                    publish()
                except OSError:
                    pass
                else:
                    raise AssertionError("expected write failure")
            expected = [target] if present else []
            ok("%s: interrupted write with existing output %s" % (operation, present),
               list(protected.iterdir()) == expected and (not present or target.read_bytes() == existing))

    # Simulate a real rebuild between sentence discovery and final publication.
    racing = tmp / "rebuilt-during-synthesis.html"
    build.assemble(meta, "", COVER, racing)
    def rebuild_during_synthesis(*args, **kwargs):
        build.assemble(dict(meta, title="Updated while speaking"), "", COVER, racing)
        return {"Hello.": wav}

    with patch.object(add_voice.platform, "system", return_value="Darwin"), \
         patch.object(sys, "argv", ["add_voice.py", str(racing), "--engine", "qwen3"]), \
         patch.object(add_voice, "qwen3_available", return_value=True), \
         patch.object(add_voice, "compress", return_value=(wav, "audio/wav")), \
         patch.object(add_voice, "qwen3_batch_synth", side_effect=rebuild_during_synthesis):
        status = add_voice.main()
    updated = racing.read_text(encoding="utf-8")
    ok("voice: a rebuild during synthesis survives the stale save attempt",
       status == 2 and "<title>Updated while speaking</title>" in updated and not add_voice.BLOCK.search(updated))

    # A clip-only change must also invalidate a pending edit based on an older deck.
    for action, data in (("embed", voice_data), ("remove", None)):
        try:
            add_voice.save_voice_data(trim_deck, before_trim, data)
        except OSError as e:
            ok("voice: stale %s preserves another clip edit" % action,
               "deck changed" in str(e) and trim_deck.read_text(encoding="utf-8") == reviewed)
        else:
            ok("voice: stale %s preserves another clip edit" % action, False)

    class _MockKokoroHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/v1/audio/voices":
                body = json.dumps({"voices": ["jf_alpha", "af_heart"]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self):
            if self.path == "/v1/audio/speech":
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n).decode("utf-8"))
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.end_headers()
                self.wfile.write(b"RIFF" + req["voice"].encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

    srv = http.server.HTTPServer(("127.0.0.1", 0), _MockKokoroHandler)
    t_srv = threading.Thread(target=srv.serve_forever, daemon=True)
    t_srv.start()
    try:
        kurl = "http://127.0.0.1:%d" % srv.server_address[1]
        ok("add_voice: find_kokoro_api detects local Kokoro server", add_voice.find_kokoro_api(kurl) == kurl)
        ok("add_voice: kokoro_api_voices lists voices", add_voice.kokoro_api_voices(kurl) == [("jf_alpha", "jf_alpha"), ("af_heart", "af_heart")])
        ok("add_voice: kokoro_api_synth posts to /v1/audio/speech", add_voice.kokoro_api_synth(kurl, "テスト", "jf_alpha", 1.0) == b"RIFFjf_alpha")
    finally:
        srv.shutdown()
        srv.server_close()

    # Batch 2 regression tests for build.py (#26-#50)
    m_ci, _, _, iss_ci, _ = build.lint("<!--\ntitle: Test\ntheme: Dark\ndensity: Dense\n-->\n<section class=\"slide title\"><h1 data-say=\"Hi.\">Hi</h1></section>\n")
    ok("build: theme and density normalized case-insensitively", m_ci["theme"] == "dark" and m_ci["density"] == "dense" and not errors(iss_ci))

    _, _, _, iss_ext_ci, _ = build.lint("<!--\ntitle: T\n-->\n<section class=\"slide\"><img src=\"HTTPS://example.com/a.png\" alt=\"a\" data-say=\"a.\"></section>\n")
    ok("build: uppercase HTTPS external URL rejected", any(i["type"] == "external" for i in errors(iss_ext_ci)))

    _, _, _, iss_ftp, _ = build.lint("<!--\ntitle: T\n-->\n<section class=\"slide\"><iframe src=\"javascript:alert(1)\"></iframe><h2 data-say=\"a.\">a</h2></section>\n")
    ok("build: javascript: URL in iframe rejected", any(i["type"] == "external" for i in errors(iss_ftp)))

    _, _, _, iss_style_url, _ = build.lint("<!--\ntitle: T\n-->\n<section class=\"slide\"><div style=\"background:url(https://example.com/bg.png)\" data-say=\"a.\">a</div></section>\n")
    ok("build: external url() in inline style rejected", any(i["type"] == "external" for i in errors(iss_style_url)))

    _, _, _, iss_empty_img, _ = build.lint("<!--\ntitle: T\n-->\n<section class=\"slide\"><img src=\"\" alt=\"a\" data-say=\"a.\"></section>\n")
    ok("build: empty img src flagged as missing-image error", any(i["type"] == "missing-image" for i in errors(iss_empty_img)))

    _, _, _, iss_no_alt, _ = build.lint("<!--\ntitle: T\n-->\n<section class=\"slide\"><img src=\"data:image/png;base64,iVBORw0KGgo=\" data-say=\"a.\"></section>\n")
    ok("build: img without alt warns missing-alt", any(i["type"] == "missing-alt" and i["level"] == "warn" for i in iss_no_alt))

    _, _, _, iss_empty_alt, _ = build.lint("<!--\ntitle: T\n-->\n<section class=\"slide\"><img src=\"data:image/png;base64,iVBORw0KGgo=\" alt=\"\" data-say=\"a.\"></section>\n")
    ok("build: decorative img with alt='' does not warn missing-alt", not any(i["type"] == "missing-alt" for i in iss_empty_alt))

    _, _, _, iss_empty_say_img, _ = build.lint("<!--\ntitle: T\n-->\n<section class=\"slide\"><img src=\"data:image/png;base64,iVBORw0KGgo=\" alt=\"a\" data-say=\"   \"></section>\n")
    ok("build: img with empty data-say warns empty-say", any(i["type"] == "empty-say" for i in iss_empty_say_img))

    _, _, _, iss_voice_cap, _ = build.lint("<!--\ntitle: T\n-->\n<section class=\"slide\"><span class=\"voice\" data-caption=\"Narration only.\"></span></section>\n")
    ok("build: .voice with data-caption only is allowed without no-narration error", not any(i["type"] in ("no-narration", "voice-empty") for i in iss_voice_cap))

    _, _, _, iss_bad_theme_line, _ = build.lint("<!--\ntitle: T\ntheme: bogus\n-->\n<section class=\"slide\"><h2 data-say=\"a.\">a</h2></section>\n")
    ok("build: unknown-theme reports exact header line number", any(i["type"] == "unknown-theme" and i.get("line") == 3 for i in iss_bad_theme_line))

    css_esc_out = tmp / "css-escape.html"
    build.assemble({"title": "A --> B\nLine2", "theme": "light", "lang": "en", "density": "normal"}, "body { content: '</style><script>alert(1)</script>'; }", COVER, css_esc_out)
    css_esc_html = css_esc_out.read_text(encoding="utf-8")
    ok("build: assemble escapes </style in custom CSS", "</style><script>alert(1)" not in css_esc_html and "<\\/style>" in css_esc_html)
    ext_san_out = tmp / "extracted-san.slides.html"
    build.extract(css_esc_out, ext_san_out)
    ext_san_txt = ext_san_out.read_text(encoding="utf-8")
    ok("build: extract sanitizes --> and newlines in header", "title: A -- > B Line2" in ext_san_txt)

    # Batch 3 regression tests for add_voice.py (#51-#75)
    try:
        add_voice.local_url("file://localhost/etc/passwd")
        ok("add_voice: local_url rejects non-http scheme", False, "did not raise")
    except SystemExit:
        ok("add_voice: local_url rejects non-http scheme", True)
    ok("add_voice: kokoro_lang_code handles uppercase voice ID", add_voice.kokoro_lang_code("AF_heart") == "a")
    nan_wav = add_voice.pcm_to_wav([float("nan"), float("inf"), -float("inf"), 0.5], 24000)
    ok("add_voice: pcm_to_wav handles NaN/Inf safely", nan_wav[:4] == b"RIFF" and len(nan_wav) == 44 + 8)
    nan_clean = add_voice.clean_speech([float("nan")] * 100 + [0.2] * 2000 + [float("inf")] * 100, 24000)
    ok("add_voice: clean_speech sanitizes non-finite samples", all(math.isfinite(x) for x in nan_clean))
    ok("add_voice: _prep_qwen3_text expands numeric-only Japanese % and ℃",
       add_voice._prep_qwen3_text("25%") == "25パーセント。" and add_voice._prep_qwen3_text("30℃") == "30度。")
    ok("add_voice: _prep_qwen3_text expands + after kanji (前年比+5件)",
       add_voice._prep_qwen3_text("前年比+5件です。") == "前年比プラス5件です。")
    ok("add_voice: _prep_qwen3_text handles 六・一日 kanji decimal day",
       add_voice._prep_qwen3_text("平均六・一日です。") == "平均六てん一にちです。")
    ok("add_voice: _prep_qwen3_text strips full-width comma in numbers",
       add_voice._prep_qwen3_text("費用は4，800円です。") == "費用は四千八百円です。")
    try:
        add_voice.save_voice_data(tmp / "no-engine.html", "<html><body>no engine</body></html>", {"clips": {}})
        ok("add_voice: save_voice_data rejects HTML without engine marker", False, "did not raise")
    except ValueError:
        ok("add_voice: save_voice_data rejects HTML without engine marker", True)
    with patch.object(sys, "argv", ["add_voice.py", str(trim_deck), "--engine", "qwen3", "--url", "http://127.0.0.1:50021"]):
        ok("add_voice: rejects --url with --engine qwen3", add_voice.main() == 2)
    with patch.object(sys, "argv", ["add_voice.py", str(tmp)]):
        ok("add_voice: rejects directory as deck path", add_voice.main() == 2)

    # Batch 4 regression tests for check.py (#76-#88)
    with patch.dict(os.environ, {"CHROME": str(tmp)}):
        ok("check: find_browser ignores directory in CHROME env", check.find_browser() != str(tmp))
    try:
        check.export_pdf(rep, tmp)
        ok("check: export_pdf rejects directory output", False)
    except check.CheckError:
        ok("check: export_pdf rejects directory output", True)
    sc_nl = tmp / "script-nl.md"
    check.export_script({"title": "Line1\nLine2", "deck": deck, "script": [{"label": "S1\nTitle", "sec": -5, "lines": ["A\nB"]}]}, sc_nl)
    sc_nl_txt = sc_nl.read_text(encoding="utf-8")
    ok("check: export_script collapses newlines and clamps negative sec",
       sc_nl_txt.startswith("# Line1 Line2\n") and "## S1 Title (0:00)" in sc_nl_txt and "- A B" in sc_nl_txt)
    vtt_edge = tmp / "edge.vtt"
    check.export_vtt({"script": [{"cues": [{"start": 1000, "end": 500, "text": "a --> b"}, {"start": None, "end": None, "text": "ok"}]}]}, vtt_edge)
    vtt_edge_txt = vtt_edge.read_text(encoding="utf-8")
    ok("check: export_vtt guards None/reversed timestamps and escapes -->",
       "00:00:01.000 --> 00:00:01.001" in vtt_edge_txt and "a -> b" in vtt_edge_txt and "00:00:00.000 --> 00:00:00.001" in vtt_edge_txt)
    ok("check: print_issues handles unknown level and negative slide index safely",
       check.print_issues([{"slide": -1, "type": "custom", "level": "info", "msg": "hi"}], lines=[10]) is False)
    r_chk_col = subprocess.run([sys.executable, str(SKILL / "scripts" / "check.py"), str(deck), "--vtt", str(deck)], capture_output=True, text=True)
    ok("check.py: refuses --vtt overwriting input deck", r_chk_col.returncode == 2)
    ext_ci_deck = built(tmp, "ext-ci.html", HEAD + '<section class="slide title"><h1 data-say="Hi.">x</h1><IMG SRC="HTTPS://example.com/x.png" alt="x"></section>')
    ok("check.inspect: catches uppercase HTTPS external URL", any(i["type"] == "external" for i in check.inspect(ext_ci_deck)["issues"]))

    # Follow-up edge-case regression tests
    _, _, _, iss_vcap_mis, _ = build.lint(HEAD + '<section class="slide"><p class="voice" data-caption="One. Two.">One.</p></section>')
    ok("build: catches caption-mismatch between .voice body and data-caption", any(i["type"] == "caption-mismatch" for i in errors(iss_vcap_mis)))
    _, _, _, iss_style_file, _ = build.lint(HEAD + '<section class="slide"><div style="background:url(file:///tmp/a.png)" data-say="Hi.">x</div></section>')
    ok("build: rejects url(file://...) in inline style", any(i["type"] == "external" for i in errors(iss_style_file)))
    vcap_only_deck = built(tmp, "vcap-only.html", HEAD + '<section class="slide"><span class="voice" data-caption="Caption fallback."></span></section>')
    ok("player: .voice with data-caption only falls back to speaking caption", check.inspect(vcap_only_deck)["texts"] == ["Caption fallback."])
    code_import_deck = built(tmp, "code-import.html", HEAD + '<section class="slide"><h2 data-say="CSS.">CSS</h2><pre><code>@import "theme.css";</code></pre></section>')
    ok("check.inspect: does not false-positive @import inside slide <code>", not any(i["type"] == "external" for i in check.inspect(code_import_deck)["issues"]))
    _, _, _, iss_css_file, _ = build.lint(HEAD + '<style>.a { background: url(file:///tmp/x.png); }</style>\n' + COVER)
    ok("build: rejects url(file://...) inside <style> block", any(i["type"] == "external" for i in errors(iss_css_file)))
    hl_src = tmp / "hl-src.slides.html"
    hl_src.write_text(HEAD + COVER, encoding="utf-8")
    hl_alias = tmp / "hl-alias.vtt"
    os.link(hl_src, hl_alias)
    r_hl = subprocess.run([sys.executable, str(SKILL / "scripts" / "build.py"), str(hl_src), "--vtt", str(hl_alias)], capture_output=True, text=True)
    ok("build.py: refuses --vtt hardlink colliding with source", r_hl.returncode == 2)
    two_s = built(tmp, "vtt-sync.html", HEAD + '<section class="slide"><h2 data-say="First. Second.">Hi</h2></section>')
    two_cues = check.inspect(two_s)["script"][0]["cues"]
    ok("player: WebVTT cues keep 250ms inter-sentence gap without double-counting",
       len(two_cues) == 2 and two_cues[1]["start"] - two_cues[0]["end"] == 250)

    # Batch 5 regression tests (bug fixes + UX/CLI improvements)
    dense_cover_small = '<!--\ntitle: D\ntheme: light\ndensity: dense\n-->\n<section class="slide title"><h1 data-say="Hi.">Hi</h1><p style="font-size:18px">small</p></section>\n'
    ok("build: dense deck still enforces 22px minimum on cover slide",
       any(i["type"] == "small-text" for i in errors(build.lint(dense_cover_small)[3])))
    dup_id_src = HEAD + '<section class="slide title"><h1 id="arr" data-say="A.">A</h1></section>\n<section class="slide"><h2 id="arr" data-say="B.">B</h2></section>\n'
    ok("build: warns on duplicate id across slides",
       any(i["type"] == "duplicate-id" and i["level"] == "warn" for i in build.lint(dup_id_src)[3]))
    r_shots_col = subprocess.run([sys.executable, str(SKILL / "scripts" / "build.py"), str(hl_src), "--shots", str(hl_src)], capture_output=True, text=True)
    ok("build.py: refuses --shots colliding with source", r_shots_col.returncode == 2)
    r_chk_json = subprocess.run([sys.executable, str(SKILL / "scripts" / "check.py"), str(deck), "--json"], capture_output=True, text=True)
    parsed_chk = json.loads(r_chk_json.stdout) if r_chk_json.returncode == 0 else {}
    ok("check.py --json: outputs valid JSON report", r_chk_json.returncode == 0 and parsed_chk.get("slides") == rep["slides"] and isinstance(parsed_chk.get("issues"), list))

    # Batch 6 regression tests (gantt lint, add_voice batch error handling, URL ?rate=&caps=0)
    bad_gantt = (
        '<!--\ntitle: G\ntheme: light\ndensity: dense\n-->\n'
        '<section class="slide title"><h1 data-say="G.">G</h1></section>\n'
        '<section class="slide"><h2 data-say="Plan.">Plan</h2>'
        '<table class="gantt"><thead><tr><th>Task</th><th>M1</th><th>M2</th><th>M3</th></tr></thead>'
        '<tbody><tr data-say="A."><th>A</th><td class="bar" colspan="2">A</td></tr></tbody></table></section>\n'
    )
    ok("build: lint catches gantt row column count mismatch",
       any(i["type"] == "gantt-columns" for i in errors(build.lint(bad_gantt)[3])))
    bad_colspan = bad_gantt.replace('colspan="2"', 'colspan="0"')
    ok("build: lint catches invalid colspan=0",
       any(i["type"] == "bad-colspan" for i in errors(build.lint(bad_colspan)[3])))
    err_deck = tmp / "qwen3-err.html"
    build.assemble(meta, "", COVER, err_deck)
    err_before = err_deck.read_bytes()
    with patch.object(add_voice.platform, "system", return_value="Darwin"), \
         patch.object(sys, "argv", ["add_voice.py", str(err_deck), "--engine", "qwen3"]), \
         patch.object(add_voice, "qwen3_available", return_value=True), \
         patch.object(add_voice, "qwen3_batch_synth", side_effect=RuntimeError("simulated model load failure")):
        rc_qerr = add_voice.main()
    ok("add_voice: qwen3_batch_synth error exits 1 without modifying deck",
       rc_qerr == 1 and err_deck.read_bytes() == err_before)
    ok("add_voice: find_voicevox handles connection refused cleanly without shadowing error",
       add_voice.find_voicevox("http://127.0.0.1:1") is None)
    ok("add_voice: find_kokoro_api handles connection refused cleanly without shadowing error",
       add_voice.find_kokoro_api("http://127.0.0.1:1") is None)
    r_rc = check.run(browser, ["--window-size=1280,720", "--virtual-time-budget=3000", "--dump-dom", deck.as_uri() + "?rate=1.5&caps=0"])
    ok("player: URL ?rate=1.5&caps=0 sets initial speed and captions off",
       '>1.5x</button>' in r_rc.stdout and 'id="b-cc"' in r_rc.stdout and 'aria-pressed="false"' in r_rc.stdout)

    # Batch 7 regression tests (WCAG AA contrast across all 10 themes, heading <br> spacing, overview SVG ID rewrite)
    tpl_txt = (SKILL / "assets" / "template.html").read_text(encoding="utf-8")
    thm_blk = re.search(r"/\* THEME:START.*?/\* THEME:END \*/", tpl_txt, re.S).group(0)
    thm_defs = re.findall(r':root(?::where\(\[data-theme="([^"]+)"\]\))?\s*\{([^}]+)\}', thm_blk)
    def _hex_lum(hx):
        hx = hx.lstrip("#")
        rgb = [int(hx[j:j + 2], 16) / 255.0 for j in (0, 2, 4)]
        rgb = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    def _cr(a, b):
        la, lb = _hex_lum(a), _hex_lum(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)
    base_vars = dict(re.findall(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})", thm_defs[0][1]))
    wcag_fails = []
    for tname, tbody in thm_defs:
        tv = dict(base_vars, **dict(re.findall(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})", tbody)))
        for fg_k in ("fg", "muted", "accent", "ok", "warn", "ng"):
            for bg_k in ("bg", "card", "accent-soft"):
                if _cr(tv[fg_k], tv[bg_k]) < 4.5:
                    wcag_fails.append("%s:%s/%s" % (tname or "light", fg_k, bg_k))
        for fg_k, bg_k in (("on-accent", "accent"), ("section-fg", "section-bg")):
            if _cr(tv[fg_k], tv[bg_k]) < 4.5:
                wcag_fails.append("%s:%s/%s" % (tname or "light", fg_k, bg_k))
    ok("themes: all 10 themes meet WCAG AA >= 4.5:1 across all colour pairs", not wcag_fails, wcag_fails)

    br_deck = built(tmp, "br-heading.html", HEAD + '<section class="slide title"><h1 data-say="Expense claims.">Expense<br>Claims</h1></section>\n<section class="slide"><h2 data-say="Diagram.">Diagram</h2><figure class="grow"><svg viewBox="0 0 200 100"><defs><marker id="arr" markerWidth="5" markerHeight="5" refX="2" refY="2.5" orient="auto"><path d="M0 0 L5 2.5 L0 5z" fill="var(--accent)"/></marker></defs><path d="M10 50 H180" stroke="var(--accent)" stroke-width="6" marker-end="url(#arr)"/></svg></figure></section>')
    br_rep = check.inspect(br_deck)
    ok("player: heading <br> preserves word spacing in aria-label and script",
       br_rep["script"][0]["label"] == "1 / 2 Expense Claims", br_rep["script"][0]["label"])
    r_ov_svg = check.run(browser, ["--window-size=1280,720", "--virtual-time-budget=3000", "--dump-dom", br_deck.as_uri() + "?overview=1"])
    ok("player: overview rewrites cloned SVG marker IDs instead of stripping them",
       'id="ov-1-arr"' in r_ov_svg.stdout and 'url(#ov-1-arr)' in r_ov_svg.stdout)

    # Batch 8 regression tests (fuzzer security/crash fixes + embedded audio E2E)
    for lbl, bad_frag, exp_type in (
        ("null byte in img src", '<img src="\x00bad.png" alt="a" data-say="a.">', "missing-image"),
        ("external srcset URL", '<img src="data:image/png;base64,AA==" srcset="https://evil.com/2x.png 2x" alt="a" data-say="a.">', "external"),
        ("external video poster", '<video poster="https://evil.com/p.jpg"></video><h2 data-say="a.">a</h2>', "external"),
        ("external object data", '<object data="https://evil.com/x.swf"></object><h2 data-say="a.">a</h2>', "external"),
        ("javascript: link href", '<a href="javascript:alert(1)" data-say="a.">a</a>', "script"),
        ("inline onclick handler", '<h2 onclick="alert(1)" data-say="a.">a</h2>', "script"),
    ):
        _, _, _, f_iss, _ = build.lint(HEAD + '<section class="slide title">' + bad_frag + '</section>', base_dir=tmp)
        ok("build: catches " + lbl, any(i["type"] == exp_type for i in errors(f_iss)), f_iss)
    ok("add_voice: clean_speech returns samples unchanged when sample_rate <= 0",
       add_voice.clean_speech([0.1, 0.2, 0.3], 0) == [0.1, 0.2, 0.3])

    # Embedded audio E2E browser test (valid WAV clips + corrupt clip fallback)
    ea_deck = tmp / "embedded-audio-e2e.html"
    ea_src = HEAD + '<section class="slide title"><h1 data-say="First clip.">First</h1></section>\n<section class="slide"><h2 data-say="Second clip.">Second</h2></section>\n'
    ea_m, ea_c, ea_s, _, _ = build.lint(ea_src)
    build.assemble(ea_m, ea_c, ea_s, ea_deck)
    ea_wav = "data:audio/wav;base64," + base64.b64encode(add_voice.pcm_to_wav([0.05] * 8000, 24000)).decode("ascii")
    add_voice.save_voice_data(ea_deck, ea_deck.read_text(encoding="utf-8"), {
        "voice": "test", "label": "Test", "speed": 1.0,
        "clips": {"First clip.": ea_wav, "Second clip.": ea_wav},
        "durations": {"First clip.": 0.33, "Second clip.": 0.33},
    })
    EA_TEST_JS = r"""<script>(async function(){
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const $ = s => document.querySelector(s);
      const all = () => [...document.querySelectorAll('#stage > section.slide')];
      const cur = () => all().findIndex(s => s.classList.contains('active')) + 1;
      const meta = $('#start-meta').textContent;
      $('#start-play').click();
      await sleep(25000);
      const pre = document.createElement('pre'); pre.id = 'eatest';
      pre.textContent = JSON.stringify({ meta, cur: cur(), ended: !$('#player').classList.contains('playing') && !$('#start').hidden });
      document.body.appendChild(pre);
    })();</script>"""
    ea_run = tmp / "ea-run.html"
    ea_run.write_text(ea_deck.read_text(encoding="utf-8").replace("</body>", EA_TEST_JS + "</body>"), encoding="utf-8")
    r_ea = check.run(browser, ["--enable-logging=stderr", "--window-size=1280,720", "--virtual-time-budget=60000", "--dump-dom", ea_run.as_uri()])
    m_ea = re.search(r'<pre id="eatest">(.*?)</pre>', r_ea.stdout, re.S)
    ea_o = json.loads(html.unescape(m_ea.group(1))) if m_ea else {}
    ok("embedded audio E2E: displays Audio badge and plays to end cleanly",
       "Audio" in ea_o.get("meta", "") and ea_o.get("cur") == 2 and ea_o.get("ended") and not js_errors(r_ea.stderr),
       (ea_o, js_errors(r_ea.stderr)[:2]))

    ea_bad = tmp / "ea-bad.html"
    build.assemble(ea_m, ea_c, ea_s, ea_bad)
    add_voice.save_voice_data(ea_bad, ea_bad.read_text(encoding="utf-8"), {
        "voice": "test", "label": "Test", "speed": 1.0,
        "clips": {"First clip.": "data:audio/wav;base64,AAAA", "Second clip.": "data:audio/wav;base64,AAAA"},
        "durations": {"First clip.": 0.33, "Second clip.": 0.33},
    })
    ea_bad.write_text(ea_bad.read_text(encoding="utf-8").replace("</body>", EA_TEST_JS + "</body>"), encoding="utf-8")
    r_eab = check.run(browser, ["--enable-logging=stderr", "--window-size=1280,720", "--virtual-time-budget=60000", "--dump-dom", ea_bad.as_uri()])
    m_eab = re.search(r'<pre id="eatest">(.*?)</pre>', r_eab.stdout, re.S)
    eab_o = json.loads(html.unescape(m_eab.group(1))) if m_eab else {}
    ok("embedded audio E2E: corrupt clip falls back cleanly and still finishes",
       eab_o.get("cur") == 2 and eab_o.get("ended") and not js_errors(r_eab.stderr),
       (eab_o, js_errors(r_eab.stderr)[:2]))

    # Batch 9 regression tests (build.py --json, link/bg/section CSS)
    r_bjson = subprocess.run([sys.executable, str(SKILL / "scripts" / "build.py"), str(starter), "-o", str(tmp / "json-out.html"), "--no-render", "--json"], capture_output=True, text=True)
    bj = json.loads(r_bjson.stdout) if r_bjson.returncode == 0 else {}
    ok("build.py --json --no-render: outputs valid JSON summary", r_bjson.returncode == 0 and bj.get("ok") is True and bj.get("built") is True and bj.get("slides") == rep["slides"])
    bad_json_src = tmp / "bad-json.slides.html"
    bad_json_src.write_text("<section class=\"slide\"><h2>no header</h2></section>", encoding="utf-8")
    r_bjson_err = subprocess.run([sys.executable, str(SKILL / "scripts" / "build.py"), str(bad_json_src), "--json"], capture_output=True, text=True)
    bje = json.loads(r_bjson_err.stdout) if r_bjson_err.stdout.strip().startswith("{") else {}
    ok("build.py --json: outputs structured JSON on lint failure", r_bjson_err.returncode == 1 and bje.get("ok") is False and bje.get("built") is False and len(bje.get("issues", [])) > 0)

    # Batch 10 regression tests (TTS closing bracket/oku-man, WebVTT XML escaping, add_voice --info)
    ok("add_voice: _prep_qwen3_text avoids double period after closing bracket",
       add_voice._prep_qwen3_text("「これはテストです。」") == "「これはテストです。」" and add_voice._prep_qwen3_text("「本当ですか？」") == "「本当ですか？」")
    ok("add_voice: _prep_qwen3_text normalizes compound 億+万円 consistently",
       add_voice._prep_qwen3_text("1億2,000万円です。") == "一億二千万円です。")
    vtt_esc = tmp / "esc.vtt"
    check.export_vtt({"script": [{"cues": [{"start": 0, "end": 1000, "text": "Use <section> & A --> B"}]}]}, vtt_esc)
    ok("check.export_vtt: escapes & and < per WebVTT spec",
       "Use &lt;section> &amp; A -> B" in vtt_esc.read_text(encoding="utf-8"))
    r_vinfo = subprocess.run([sys.executable, str(SKILL / "scripts" / "add_voice.py"), str(ea_deck), "--info"], capture_output=True, text=True)
    ok("add_voice --info: reports embedded clip count, format and duration",
       r_vinfo.returncode == 0 and "Clips: 2" in r_vinfo.stdout and "audio/wav" in r_vinfo.stdout and "Duration:" in r_vinfo.stdout, r_vinfo.stdout)
    r_vinfo_empty = subprocess.run([sys.executable, str(SKILL / "scripts" / "add_voice.py"), str(deck), "--info"], capture_output=True, text=True)
    ok("add_voice --info: reports cleanly when no audio is embedded",
       r_vinfo_empty.returncode == 0 and "No embedded audio" in r_vinfo_empty.stdout, r_vinfo_empty.stdout)

    # Batch 11 regression tests (quoted/parenthesized sentence splitting parity, kicker/quote slide titles, dark PDF notes bg)
    quote_sents = 'He said "Done." Wait (really!). Next.) End.'
    expected_q = ['He said "Done."', 'Wait (really!).', 'Next.)', 'End.']
    ok("build.sentences: splits quoted and parenthesized English sentences cleanly", build.sentences(quote_sents) == expected_q, build.sentences(quote_sents))
    qs_deck = built(tmp, "quote-split.html", HEAD + '<section class="slide tc"><p class="kicker">KPI</p><p class="stat" data-say=\'' + quote_sents + '\'>99%</p></section>')
    qs_rep = check.inspect(qs_deck)
    ok("player: split() matches build.sentences() on quoted/parenthesized text", qs_rep["texts"] == expected_q, qs_rep["texts"])
    ok("player: stat slide without h1/h2 uses .kicker as slide label", qs_rep["script"][0]["label"] == "1 / 1 KPI", qs_rep["script"][0]["label"])

    # Batch 12 regression tests (CC icon evenodd, mobile #b-help hidden, footer --lift clears .source, #blank focus)
    tpl_text = (SKILL / "assets" / "template.html").read_text(encoding="utf-8")
    ok("template: #b-cc SVG path uses fill-rule=evenodd so caption bars cut out", 'id="b-cc"' in tpl_text and 'fill-rule="evenodd"' in tpl_text)
    ok("template: #b-help mobile hide selector beats #btns button specificity", "#voice, #btns #b-help { display: none; }" in tpl_text)
    lift_js = """<script>(function(){
      var f = document.querySelector('.slide.active .slide-footer');
      var src = document.querySelector('.slide.active .source');
      var b = document.getElementById('blank');
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'b', bubbles: true }));
      var blankFocused = document.activeElement === b && !b.hidden;
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      var pre = document.createElement('pre'); pre.id = 'ltest';
      pre.textContent = JSON.stringify({
        fTop: f.getBoundingClientRect().top,
        srcBot: src.getBoundingClientRect().bottom,
        blankFocused: blankFocused
      });
      document.body.appendChild(pre);
    })();</script>"""
    lift_html = tmp / "lift-test.html"
    lift_html.write_text((ROOT / "examples" / "tablet-proposal.html").read_text(encoding="utf-8").replace("</body>", lift_js + "</body>"), encoding="utf-8")
    r_lift = check.run(browser, ["--window-size=1280,720", "--virtual-time-budget=2000", "--dump-dom", lift_html.as_uri() + "?noanim=1#2"])
    m_lift = re.search(r'<pre id="ltest">(.*?)</pre>', r_lift.stdout, re.S)
    lift_o = json.loads(html.unescape(m_lift.group(1))) if m_lift else {}
    ok("player: lifted footer stays below .source on dense slides and #blank receives focus",
       lift_o.get("fTop", 0) >= lift_o.get("srcBot", 999) and lift_o.get("blankFocused") is True, lift_o)

    # Batch 13 regression tests (HTMLParser external check, SVG <image> inlining, self-closing non-void HTML, CLI JSON/collisions)
    ok("check: ignores url(https://...) inside slide <code> and HTML comments",
       not check.has_external_resources('<pre><code>background: url(https://example.com/a.png);</code></pre><!-- <img src="https://evil.com/x.png"> -->'))
    ok("check: ignores data:image/svg+xml with http:// XML namespace",
       not check.has_external_resources('<img src="data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22/>">'))
    ok("check: catches unquoted external img src and inline style url()",
       check.has_external_resources('<img src=https://evil.com/x.png alt=x>') and check.has_external_resources('<div style="background:url(https://evil.com/bg.png)"></div>'))
    ok("check: catches external url() in <style> while ignoring CSS comments",
       check.has_external_resources('<style>body{background:url(https://evil.com/a.png)}</style>') and not check.has_external_resources('<style>/* url(https://example.com/comment) */ body{color:#000}</style>'))
    sc_iss = build.lint(HEAD + '<section class="slide title"><h1 data-say="Hi.">Hi</h1><div class="card" /><p>next</p></section>')[3]
    ok("build: rejects non-void self-closing HTML tag outside SVG", any(i["type"] == "self-closing" for i in errors(sc_iss)), sc_iss)
    ok("build: allows self-closing SVG shapes inside <svg>", not errors(build.lint(HEAD + '<section class="slide title"><h1 data-say="Hi.">Hi</h1><svg viewBox="0 0 100 100"><rect width="10" height="10"/></svg></section>')[3]))
    svg_img_dir = tmp / "svgimg"
    svg_img_dir.mkdir(exist_ok=True)
    (svg_img_dir / "tiny.png").write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII="))
    svg_src = HEAD + '<section class="slide title"><h1 data-say="Hi.">Hi</h1><svg viewBox="0 0 100 100"><image href="tiny.png" width="50" height="50"/></svg></section>'
    sm, sc_css, ssl, s_iss, _ = build.lint(svg_src, base_dir=svg_img_dir)
    svg_out = svg_img_dir / "out.html"
    build.assemble(sm, sc_css, ssl, svg_out, base_dir=svg_img_dir)
    ok("build: embeds local SVG <image href> as data URI", not errors(s_iss) and "data:image/png;base64," in svg_out.read_text(encoding="utf-8"))
    miss_svg = build.lint(HEAD + '<section class="slide title"><h1 data-say="Hi.">Hi</h1><svg viewBox="0 0 100 100"><image href="nope.png" width="50" height="50"/></svg></section>', base_dir=svg_img_dir)[3]
    ok("build: catches missing local SVG <image href>", any(i["type"] == "missing-image" for i in errors(miss_svg)), miss_svg)
    r_dup_b = subprocess.run([sys.executable, str(SKILL / "scripts" / "build.py"), str(starter), "--pdf", str(tmp / "same.out"), "--script", str(tmp / "same.out"), "--json"], capture_output=True, text=True)
    ok("build.py --json: rejects duplicate export target with valid JSON", r_dup_b.returncode == 2 and json.loads(r_dup_b.stdout).get("ok") is False, r_dup_b.stdout)
    r_dup_c = subprocess.run([sys.executable, str(SKILL / "scripts" / "check.py"), str(deck), "--pdf", str(tmp / "same.out"), "--vtt", str(tmp / "same.out"), "--json"], capture_output=True, text=True)
    ok("check.py --json: rejects duplicate export target with valid JSON", r_dup_c.returncode == 2 and "error" in json.loads(r_dup_c.stdout), r_dup_c.stdout)

    # Batch 14 regression tests (add_voice afconvert 24kHz AAC & trim, yen/quote TTS, voicevox mock, dry-run, --json, say speaker check)
    ok("add_voice: _prep_qwen3_text avoids double period after typographic closing quotes",
       add_voice._prep_qwen3_text("“完了です。”") == "“完了です。”" and add_voice._prep_qwen3_text("‘OK.’") == "‘OK.’")
    ok("add_voice: _prep_qwen3_text normalizes yen-prefixed amounts (¥1,200 / ￥120,000)",
       add_voice._prep_qwen3_text("月額¥1,200です。") == "月額千二百円です。" and add_voice._prep_qwen3_text("予算は￥120,000です。") == "予算は十二万円です。")
    if shutil.which("afconvert"):
        real_which = shutil.which
        with patch.object(add_voice.shutil, "which", side_effect=lambda cmd: None if cmd == "ffmpeg" else real_which(cmd)):
            m4a_raw, m4a_mime = add_voice.compress(add_voice.pcm_to_wav([0.1] * 24000, 24000), ".wav", tmp)
            ok("add_voice: afconvert compresses 24kHz mono WAV to M4A without ffmpeg", m4a_mime == "audio/mp4" and len(m4a_raw) > 0, (m4a_mime, len(m4a_raw)))
            m4a_uri = "data:audio/mp4;base64," + base64.b64encode(m4a_raw).decode("ascii")
            trimmed_uri = add_voice.trim_clip(m4a_uri, 0.4)
            ok("add_voice: trim_clip decodes M4A via afconvert when ffmpeg is unavailable", trimmed_uri.startswith("data:audio/wav;base64,"))
    class _MockVoicevoxHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/version":
                body = json.dumps("0.20.0").encode("utf-8")
            elif self.path == "/speakers":
                body = json.dumps([{"name": "四国めたん", "styles": [{"id": 2, "name": "ノーマル"}]}]).encode("utf-8")
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path.startswith("/audio_query?"):
                body = json.dumps({"speedScale": 1.0}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/synthesis?"):
                n = int(self.headers.get("Content-Length", 0))
                q = json.loads(self.rfile.read(n).decode("utf-8"))
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.end_headers()
                self.wfile.write(b"RIFF" + str(q.get("speedScale")).encode("utf-8"))
            else:
                self.send_response(404)
                self.end_headers()

    vv_srv = http.server.HTTPServer(("127.0.0.1", 0), _MockVoicevoxHandler)
    threading.Thread(target=vv_srv.serve_forever, daemon=True).start()
    try:
        vurl = "http://127.0.0.1:%d" % vv_srv.server_address[1]
        ok("add_voice: find_voicevox detects local VOICEVOX server", add_voice.find_voicevox(vurl) == vurl)
        ok("add_voice: voicevox_speakers parses speaker styles", add_voice.voicevox_speakers(vurl) == [(2, "四国めたん（ノーマル）")])
        ok("add_voice: voicevox_synth applies speedScale and returns WAV bytes", add_voice.voicevox_synth(vurl, "テスト", 2, 1.2) == b"RIFF1.2")
    finally:
        vv_srv.shutdown()
        vv_srv.server_close()
    r_vinfo_j = subprocess.run([sys.executable, str(SKILL / "scripts" / "add_voice.py"), str(ea_deck), "--info", "--json"], capture_output=True, text=True)
    vi_j = json.loads(r_vinfo_j.stdout) if r_vinfo_j.returncode == 0 else {}
    ok("add_voice --info --json: outputs structured audio summary", r_vinfo_j.returncode == 0 and vi_j.get("has_audio") is True and vi_j.get("clips") == 2 and vi_j.get("duration_sec", 0) > 0, vi_j)
    r_dry = subprocess.run([sys.executable, str(SKILL / "scripts" / "add_voice.py"), str(ea_deck), "--dry-run", "--json"], capture_output=True, text=True)
    dry_j = json.loads(r_dry.stdout) if r_dry.returncode == 0 else {}
    ok("add_voice --dry-run --json: lists sentences and cache status without an engine",
       r_dry.returncode == 0 and dry_j.get("total") == 2 and dry_j.get("cached") == 2 and dry_j.get("new") == 0, dry_j)
    with patch.object(add_voice.shutil, "which", return_value="/usr/bin/say"), \
         patch.object(add_voice, "say_voices", return_value=[("Kyoko", "ja_JP"), ("Samantha", "en_US")]), \
         patch.object(sys, "argv", ["add_voice.py", str(ea_deck), "--engine", "say", "--speaker", "NoSuchVoice"]):
        ok("add_voice: --engine say rejects unknown --speaker early", add_voice.main() == 2)

    fails = [x for x in results if not x[1]]
    for name, passed, info in results:
        if not passed:
            print("FAIL  %s  %s" % (name, str(info)[:300]))
    print("%d tests: %d passed, %d failed" % (len(results), len(results) - len(fails), len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
