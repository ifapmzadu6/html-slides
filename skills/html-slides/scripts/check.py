#!/usr/bin/env python3
"""Render a built deck in a real browser and check it (overflow, text too small, missing narration, ...).

build.py calls this automatically, so there is normally no need to run it directly. Standalone use:
  python3 check.py deck.html                 # check only
  python3 check.py deck.html --shots outdir  # also save a PNG of every slide (1280x720) and two phone views
  python3 check.py deck.html --pdf deck.pdf  # also export as PDF (add --pdf-notes for speaker notes)
  python3 check.py deck.html --script deck.md  # also export the narration script as Markdown
  python3 check.py deck.html --vtt deck.vtt    # also export timed captions as WebVTT (.vtt)

Uses headless Chrome / Edge / Chromium. If none is found, set the CHROME environment variable to its path.
Exit codes: 0 = no errors, 1 = errors found, 2 = could not run (no browser, ...)
"""
import argparse
import html
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
NAMES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "msedge", "chrome"]

# How to fix each kind of finding. Written as concrete edits so that a smaller model knows the next step.
HINTS = {
    "overflow": "Cut content (at most 4 bullets of about 20 characters each; at most 2 lines of text in a card), or split the slide in two. Do NOT shrink the text to make it fit.",
    "small-text": "If that element (or a parent) sets font-size in a style attribute, remove it. If the content then does not fit, cut content. Minimum size: 22px standard, 14px on dense slides.",
    "no-narration": 'Add data-say="a narration sentence." to the heading and to each item on that slide.',
    "long-caption": "Split that sentence in two at a 。 (or a full stop). If the element has data-caption, split both data-say and data-caption at the same place.",
    "long-slide": "Split the slide in two.",
    "symbol": "Replace the symbol in the narration with words (→ becomes から / そして, 〜 becomes から, ／ becomes や / または, ＝ becomes は). The on-screen text may keep the symbol.",
    "broken-image": "Check that the image path exists relative to the .slides.html file and is a valid PNG, JPEG, WebP, GIF or SVG image.",
    "voice-stale": "Run add_voice.py again.",
}
LABEL = {"error": "ERROR", "warn": "WARNING"}


class CheckError(Exception):
    pass


def find_browser():
    env = os.environ.get("CHROME")
    if env and os.path.exists(env):
        return env
    if sys.platform == "win32":
        for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            root = os.environ.get(key)
            if root:
                for app in ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe"):
                    candidate = pathlib.Path(root) / app
                    if candidate.is_file():
                        return str(candidate)
    for p in CANDIDATES:
        if os.path.exists(p):
            return p
    for n in NAMES:
        p = shutil.which(n)
        if p:
            return p
    return None


def setup_console():
    """Force UTF-8 output. On Windows, piped output defaults to cp932, which garbles text or raises."""
    for st in (sys.stdout, sys.stderr):
        try:
            if st.isatty():
                st.reconfigure(errors="replace")
            else:
                st.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def run(browser, args, timeout=120):
    # On Windows the browser may still hold profile files just after exiting, so cleanup failures are ignored.
    prof = tempfile.mkdtemp(prefix="html-slides-prof-")
    try:
        cmd = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               "--disable-background-networking", "--disable-component-update", "--disable-sync",
               "--hide-scrollbars", "--user-data-dir=" + prof] + args
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raise CheckError("The browser did not respond within %d seconds. Run the command again." % timeout)
    except OSError as e:
        raise CheckError("The browser could not be started (%s): %s" % (browser, e))
    finally:
        shutil.rmtree(prof, ignore_errors=True)


def inspect(deck):
    """Render the deck and return the check report (dict). Raises CheckError when the check cannot run."""
    deck = pathlib.Path(deck).resolve()
    if not deck.is_file():
        raise CheckError("File not found: %s" % deck)
    try:
        src = deck.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise CheckError("Could not read %s: %s" % (deck, e)) from e
    for marker in ("SLIDES:START", "SLIDES:END", "ENGINE JS"):
        if marker not in src:
            raise CheckError("This HTML was not built by this skill's build.py (marker '%s' is missing). Rebuild it from the source with build.py." % marker)
    browser = find_browser()
    if not browser:
        raise CheckError("Chrome / Edge was not found, so the rendered check cannot run. Set the CHROME environment variable to the browser's path.")
    r = run(browser, ["--window-size=1280,720", "--virtual-time-budget=5000", "--dump-dom", deck.as_uri() + "?check=1"])
    m = re.search(r'<pre id="check-report">(.*?)</pre>', r.stdout, re.S)
    if not m:
        raise CheckError("No check report came back. Look for a <script> or broken HTML in the source.\n" + r.stderr[-500:])
    rep = json.loads(html.unescape(m.group(1)))
    for i in rep["issues"]:
        i.setdefault("level", "error")
    if re.search(r"<(script|link|img|iframe|image|use|video|audio|source)\b[^>]*(src|href)=[\"'](https?:)?//|url\([\"']?(https?:)?//|@import", src):
        rep["issues"].append({"slide": 0, "type": "external", "level": "error",
                              "msg": "The deck loads an external URL. It will not show offline or when the file is opened by double-click.",
                              "hint": "Embed images as a data URI or inline SVG. Do not load external CSS, fonts or scripts."})
    rep["browser"] = browser
    rep["deck"] = deck
    return rep


def shots(rep, outdir):
    """Save a screenshot of every slide plus phone portrait and landscape views."""
    out = pathlib.Path(outdir).resolve()
    browser, url = rep["browser"], rep["deck"].as_uri()
    stats = rep.get("stats") or [{"chars": 0}]
    dense = max(range(len(stats)), key=lambda k: stats[k].get("chars", 0)) + 1

    def capture(png, page, width, height, budget):
        result = run(browser, ["--window-size=%d,%d" % (width, height), "--virtual-time-budget=%d" % budget,
                               "--screenshot=" + str(png), page])
        if result.returncode or not png.is_file() or not png.stat().st_size:
            raise CheckError("%s could not be saved. %s" % (png.name, result.stderr[-500:]))

    try:
        out.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=out) as temp:
            stage = pathlib.Path(temp)
            for n in range(1, rep["slides"] + 1):
                capture(stage / ("slide-%02d.png" % n), "%s?still=1#%d" % (url, n), 1280, 720, 3000)
            # Scale a phone-sized iframe to fit the minimum headless window width.
            wrap = stage / "phone.html"
            for name, w, h in (("mobile-portrait", 390, 844), ("mobile-landscape", 844, 390)):
                z = 2 if w < 500 else 1
                wrap.write_text('<!DOCTYPE html><body style="margin:0;background:#000;overflow:hidden"><iframe src="%s?capdemo=1#%d" style="border:0;display:block;width:%dpx;height:%dpx;transform:scale(%d);transform-origin:0 0"></iframe>'
                                % (url, dense, w, h, z), encoding="utf-8")
                capture(stage / (name + ".png"), wrap.as_uri(), w * z, h * z, 4000)
            for png in stage.glob("*.png"):
                png.replace(out / png.name)
            for old in out.glob("slide-*.png"):
                match = re.fullmatch(r"slide-([0-9]{2,})\.png", old.name)
                if match and old.is_file():
                    number = int(match[1])
                    if number > rep["slides"] and old.name == "slide-%02d.png" % number:
                        old.unlink()
    except OSError as e:
        raise CheckError("Could not write screenshots to %s: %s" % (out, e)) from e
    return out, dense


def export_pdf(rep, out_path, notes=False):
    """Export the deck as a PDF using headless Chrome/Edge (with optional speaker notes)."""
    out = pathlib.Path(out_path).resolve()
    browser = rep["browser"]
    url = rep["deck"].as_uri() + ("?notes=1" if notes else "")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=out.parent) as temp:
            tmp = pathlib.Path(temp) / "export.pdf"
            result = run(browser, ["--no-pdf-header-footer", "--virtual-time-budget=3000",
                                   "--print-to-pdf=" + str(tmp), url])
            if result.returncode or not tmp.is_file() or not tmp.stat().st_size:
                raise CheckError("%s could not be saved. %s" % (out.name, result.stderr[-500:]))
            tmp.replace(out)
    except OSError as e:
        raise CheckError("Could not write PDF to %s: %s" % (out, e)) from e
    return out


def _write_atomic(out, text):
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent) as temp:
        tmp = pathlib.Path(temp) / out.name
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(out)


def export_script(rep, out_path):
    """Export the deck's narration script as Markdown."""
    out = pathlib.Path(out_path).resolve()
    title = rep.get("title") or rep["deck"].stem
    parts = ["# " + title, ""]
    for item in rep.get("script") or []:
        sec = int(item.get("sec") or 0)
        parts.append("## %s (%d:%02d)" % (item.get("label") or "", sec // 60, sec % 60))
        for line in item.get("lines") or []:
            parts.append("- " + line)
        parts.append("")
    try:
        _write_atomic(out, "\n".join(parts))
    except OSError as e:
        raise CheckError("Could not write script to %s: %s" % (out, e)) from e
    return out


def _vtt_time(ms):
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return "%02d:%02d:%02d.%03d" % (h, m, s, ms)


def export_vtt(rep, out_path):
    """Export the deck's captions with timestamps as WebVTT (.vtt)."""
    out = pathlib.Path(out_path).resolve()
    parts = ["WEBVTT", ""]
    idx = 0
    for item in rep.get("script") or []:
        for cue in item.get("cues") or []:
            text = re.sub(r"\s+", " ", cue.get("text") or "").strip()
            if not text:
                continue
            idx += 1
            parts.append(str(idx))
            parts.append("%s --> %s" % (_vtt_time(cue.get("start", 0)), _vtt_time(cue.get("end", 0))))
            parts.append(text.replace("-->", "->"))
            parts.append("")
    try:
        _write_atomic(out, "\n".join(parts))
    except OSError as e:
        raise CheckError("Could not write WebVTT to %s: %s" % (out, e)) from e
    return out


def report(rep, lines=None, extra=None):
    """Print the report. `lines` maps each slide to its source line. Returns True when there are errors."""
    issues = list(extra or []) + rep.get("issues", [])
    stats = rep.get("stats") or []
    if stats:
        print("Narration per slide (aim for 10-30 seconds each)")
        for k, st in enumerate(stats, 1):
            note = "  <- long (consider splitting in two)" if st["sec"] > 45 else ""
            print("  slide %2d: %d sentence(s), about %2d s%s" % (k, st["sentences"], st["sec"], note))
    print("Total: %d slides, about %d s, embedded audio: %s" % (rep["slides"], rep["totalSec"],
          ("%d sentences" % rep["clips"]) if rep.get("clips") else "none (the viewer's device voice reads it)"))
    return print_issues(issues, lines)


def print_issues(issues, lines=None):
    ng = [i for i in issues if i.get("level", "error") == "error"]
    warn = [i for i in issues if i.get("level") == "warn"]
    for i in ng + warn:
        where = []
        if i.get("slide"):
            where.append("slide %d" % i["slide"])
        line = i.get("line") or (lines[i["slide"] - 1] if lines and i.get("slide") and i["slide"] <= len(lines) else None)
        if line:
            where.append("source line %d%s" % (line, "" if i.get("line") else "+"))
        print("%s [%s] %s: %s" % (LABEL[i.get("level", "error")], ", ".join(where) or "deck", i["type"], i["msg"]))
        hint = i.get("hint") or HINTS.get(i["type"])
        if hint:
            print("    Fix: " + hint)
    if ng:
        print("RESULT: %d ERROR(S)%s - apply each Fix to the source, then run the same command again." % (len(ng), (", %d warning(s)" % len(warn)) if warn else ""))
    elif warn:
        print("RESULT: OK (%d warning(s) - leave them if they are intentional)" % len(warn))
    else:
        print("RESULT: OK (no problems found)")
    return bool(ng)


def main():
    setup_console()
    ap = argparse.ArgumentParser(description="Render a built deck and check it")
    ap.add_argument("deck")
    ap.add_argument("--shots", metavar="DIR", help="folder to save screenshots in")
    ap.add_argument("--pdf", metavar="FILE", help="export the deck as a PDF file")
    ap.add_argument("--pdf-notes", action="store_true", help="include speaker notes in the exported PDF")
    ap.add_argument("--script", metavar="FILE", help="export the narration script as Markdown")
    ap.add_argument("--vtt", metavar="FILE", help="export timed captions as WebVTT (.vtt)")
    a = ap.parse_args()
    if a.pdf_notes and not a.pdf:
        print("ERROR: --pdf-notes requires --pdf FILE.")
        return 2
    try:
        rep = inspect(a.deck)
    except CheckError as e:
        print("The check could not run: %s" % e)
        return 2
    bad = report(rep)
    if a.shots:
        try:
            out, dense = shots(rep, a.shots)
        except CheckError as e:
            print("Screenshots could not be saved: %s" % e)
            return 1 if bad else 2
        print("Screenshots: %s (slide-01.png ..., plus phone views mobile-portrait.png / mobile-landscape.png showing slide %d)" % (out, dense))
    if a.pdf:
        try:
            pdf_out = export_pdf(rep, a.pdf, notes=a.pdf_notes)
        except CheckError as e:
            print("PDF could not be saved: %s" % e)
            return 1 if bad else 2
        print("PDF: %s%s" % (pdf_out, " (with speaker notes)" if a.pdf_notes else ""))
    if a.script:
        try:
            sc_out = export_script(rep, a.script)
        except CheckError as e:
            print("Script could not be saved: %s" % e)
            return 1 if bad else 2
        print("Script: %s" % sc_out)
    if a.vtt:
        try:
            vtt_out = export_vtt(rep, a.vtt)
        except CheckError as e:
            print("WebVTT could not be saved: %s" % e)
            return 1 if bad else 2
        print("WebVTT: %s" % vtt_out)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
