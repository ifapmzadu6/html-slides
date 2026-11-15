#!/usr/bin/env python3
"""Render a built deck in a real browser and check it (overflow, text too small, missing narration, ...).

build.py calls this automatically, so there is normally no need to run it directly. Standalone use:
  python3 check.py deck.html                 # check only
  python3 check.py deck.html --shots outdir  # also save a PNG of every slide (1280x720) and two phone views

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
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
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
    "voice-stale": "Run add_voice.py again.",
}
LABEL = {"error": "ERROR", "warn": "WARNING"}


class CheckError(Exception):
    pass


def find_browser():
    env = os.environ.get("CHROME")
    if env and os.path.exists(env):
        return env
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
    if not deck.exists():
        raise CheckError("File not found: %s" % deck)
    src = deck.read_text(encoding="utf-8")
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
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("slide-[0-9][0-9].png"):  # drop leftovers from an earlier build with more slides
        old.unlink()
    browser, url = rep["browser"], rep["deck"].as_uri()
    for n in range(1, rep["slides"] + 1):
        png = out / ("slide-%02d.png" % n)
        run(browser, ["--window-size=1280,720", "--virtual-time-budget=3000", "--screenshot=" + str(png), "%s?still=1#%d" % (url, n)])
        if not png.exists():
            raise CheckError("%s could not be saved." % png.name)
    # Phone views: the slide with the most text, fully revealed, with a caption showing.
    # A headless window cannot be narrower than about 500px, so a phone-sized iframe is scaled up to fill the window.
    stats = rep.get("stats") or [{"chars": 0}]
    dense = max(range(len(stats)), key=lambda k: stats[k].get("chars", 0)) + 1
    for name, w, h in (("mobile-portrait", 390, 844), ("mobile-landscape", 844, 390)):
        z = 2 if w < 500 else 1
        wrap = out / ("_" + name + ".html")
        wrap.write_text('<!DOCTYPE html><body style="margin:0;background:#000;overflow:hidden"><iframe src="%s?capdemo=1#%d" style="border:0;display:block;width:%dpx;height:%dpx;transform:scale(%d);transform-origin:0 0"></iframe>'
                        % (url, dense, w, h, z), encoding="utf-8")
        run(browser, ["--window-size=%d,%d" % (w * z, h * z), "--virtual-time-budget=4000", "--screenshot=" + str(out / (name + ".png")), wrap.as_uri()])
        wrap.unlink()
    return out, dense


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
    a = ap.parse_args()
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
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
