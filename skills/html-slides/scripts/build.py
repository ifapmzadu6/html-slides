#!/usr/bin/env python3
"""Lint a slide source file (.slides.html) and assemble the finished single-file HTML deck.

Usage:
  python3 build.py deck.slides.html                    # lint, build deck.html, render-check it
  python3 build.py deck.slides.html --shots shots      # also save screenshots
  python3 build.py deck.slides.html -o out/deck.html   # choose the output path
  python3 build.py deck.slides.html --no-render        # lint and assemble only (no browser needed)
  python3 build.py --extract deck.html                 # recover the source (deck.slides.html) from a built deck

Two checks run:
  1. Source lint (no browser): unknown class / attribute / theme names, unclosed tags,
     slides without narration, and so on. Any ERROR stops the build before assembling.
  2. Rendered check (needs Chrome or Edge): overflow, text that is too small, captions that are too long.
Every finding carries the source line number and a "Fix:" line. Edit the source and rerun
until the last line says "RESULT: OK".

Source format (the leading comment holds the settings, the rest is slides):
  <!--
  title: 経費精算のやり方
  theme: light
  -->
  <section class="slide title"> ... </section>
  <section class="slide"> ... </section>

Settings:
  title    shown on the start screen and the browser tab (required)
  theme    colour scheme name
  lang     narration language (default: ja)
  density  "dense" switches to the smaller type and tighter spacing used for business documents
  footer   text shown bottom-left on every slide except the cover (e.g. 社外秘 ｜ 経営企画部);
           when present, a page number is shown bottom-right

Exit codes: 0 = no errors, 1 = errors found, 2 = could not run (file missing, no browser, ...)
"""
import argparse
import difflib
import html
import pathlib
import re
import sys
from html.parser import HTMLParser

HERE = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # keep __pycache__ out of the skill folder
sys.path.insert(0, str(HERE))
import check  # noqa: E402

TEMPLATE = HERE.parent / "assets" / "template.html"
REGION = re.compile(r"(<!-- SLIDES:START[^\n]*-->\n).*?(<!-- SLIDES:END -->)", re.S)
CUSTOM = re.compile(r'<style id="custom">\n?(.*?)\n?</style>\n', re.S)
VOICE_BLOCK = re.compile(r"<!-- VOICE:START -->.*?<!-- VOICE:END -->\n?", re.S)
ENGINE_MARKER = "<script>\n/* ===== ENGINE JS"
HEADER = re.compile(r"\A\s*<!--(.*?)-->", re.S)

THEMES = ["light", "dark", "corporate", "warm", "forest", "sakura", "mono", "pop", "neon", "chalk"]
SLIDE_CLASSES = ["slide", "title", "section", "end", "tc", "top", "dense", "center"]
CLASSES = ["kicker", "sub", "big", "note", "badge", "grow", "cols", "card", "emoji", "emoji-xl", "stat", "flow", "voice",
           "lead", "rows", "box", "arrows", "source", "tag", "ok", "warn", "ng", "num", "total", "matrix", "gantt", "bar", "alt"]
DATA_ATTRS = ["data-say", "data-caption", "data-anim", "data-bleed", "data-noplay"]
ANIMS = ["fade", "zoom", "pop", "left", "right"]
VOID = {"br", "img", "hr", "input", "meta", "link", "source", "col", "wbr", "area", "embed", "track"}
OPTIONAL_END = {"li", "p", "td", "th", "tr", "tbody", "thead", "tfoot", "dd", "dt", "option"}
EXTERNAL_TAGS = {"img", "script", "link", "iframe", "video", "audio", "source", "image", "use", "embed", "object"}
INSIDE_SLIDES = 'Put all content inside <section class="slide"> ... </section>.'
NO_EXTERNAL = "Embed images as a data URI or inline SVG. Do not load external CSS, fonts or scripts."


def fail(msg):
    print("ERROR: " + msg)
    sys.exit(2)


def near(word, choices):
    m = difflib.get_close_matches(word, choices, n=1, cutoff=0.6)
    return 'Did you mean "%s"? ' % m[0] if m else ""


def sentences(t):
    """Split text into sentences with the same rules as the player (split() in template.html)."""
    t = re.sub(r"\s+", " ", t or "")
    t = re.sub(r"([^\x00-\x7F])\s+(?=[^\x00-\x7F])", r"\1", t).strip()
    out, b, i = [], "", 0
    while i < len(t):
        ch = t[i]
        b += ch
        if ch in "。！？!?" or (ch == "." and (i == len(t) - 1 or t[i + 1] == " ")):
            while i + 1 < len(t) and t[i + 1] in "。！？!?」』）)":
                i += 1
                b += t[i]
            if b.strip():
                out.append(b.strip())
            b = ""
        i += 1
    if b.strip():
        out.append(b.strip())
    return out


def read_source(path):
    try:
        return path.read_text(encoding="utf-8-sig")  # tolerate a leading BOM
    except UnicodeDecodeError:
        fail("%s is not valid UTF-8. Save the file as UTF-8 and run again." % path)


class Lint(HTMLParser):
    """Source lint. Collects {line, type, level, msg, hint} dicts in self.issues."""

    def __init__(self, custom_classes, dense=False):
        super().__init__(convert_charrefs=True)
        self.custom = custom_classes
        self.deck_dense = dense
        self.issues = []
        self.stack = []     # open tags: dict(tag, line, cls, kids, text)
        self.slides = []    # dict(line, cls, cues)
        self.in_style = False

    def add(self, level, typ, msg, hint, line=None):
        self.issues.append({"line": line or self.getpos()[0], "type": typ, "level": level, "msg": msg, "hint": hint,
                            "slide": len(self.slides) if self.in_slide() else 0})

    def in_slide(self):
        return any(e["tag"] == "section" for e in self.stack)

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if tag == "style":
            self.in_style = True
            return
        if tag in ("html", "head", "body"):
            self.add("error", "whole-page", "The source contains a <%s> document tag." % tag, INSIDE_SLIDES)
        if tag == "script":
            self.add("error", "script", "<script> is not allowed in the source.",
                     "Remove the <script>. The player supplies all behaviour; use data-say and data-anim only.")
        if tag == "section":
            if self.in_slide():
                self.add("error", "nested", "A <section> is nested inside another <section>.",
                         'Close the previous slide with </section> before starting the next <section class="slide">.')
            if "slide" not in cls:
                self.add("error", "no-slide-class", '<section> has no class="slide".', 'Write <section class="slide">.')
            for c in cls:
                if c not in SLIDE_CLASSES and c not in self.custom:
                    self.add("error", "unknown-class", 'Class "%s" cannot be used on a slide.' % c,
                             near(c, SLIDE_CLASSES) + "Slide-level classes are: " + ", ".join(SLIDE_CLASSES[1:])
                             + ". The layout inside a slide is chosen by classes on the elements inside it.")
            if "data-say" in a:
                self.add("error", "say-on-section", "data-say cannot be put on the <section> itself.",
                         "Put data-say on the heading or the items inside the slide.")
            self.slides.append({"line": line, "cls": cls, "cues": 0})
        elif not self.in_slide():
            self.add("error", "outside", "<%s> is outside any slide." % tag, INSIDE_SLIDES)
        else:
            for c in cls:
                if c not in CLASSES and c not in self.custom:
                    wrong_place = ('This class belongs on the slide (<section>). Move it: <section class="slide %s">.' % c) if c in SLIDE_CLASSES else ""
                    self.add("error", "unknown-class", 'Class "%s" is not defined (it has no effect).' % c,
                             wrong_place or (near(c, CLASSES) + "Available classes: " + ", ".join(CLASSES)
                                             + ". See references/layouts.md. To use a class of your own, define it in a <style> block in the source."))
        if self.stack:
            self.stack[-1]["kids"] += 1
        for k, v in attrs:
            if k.startswith("data-") and k not in DATA_ATTRS:
                self.add("error", "unknown-attr", 'Attribute "%s" is not recognised (it has no effect).' % k,
                         near(k, DATA_ATTRS) + "Narration is data-say, the caption spelling is data-caption, the entrance animation is data-anim.")
        if "data-anim" in a and a["data-anim"] not in ANIMS:
            self.add("error", "unknown-anim", 'data-anim="%s" is not a valid animation.' % a["data-anim"],
                     near(a["data-anim"] or "", ANIMS) + "Valid values: " + ", ".join(ANIMS) + " (omit the attribute for the default rise-in).")
        if "data-anim" in a and "data-say" not in a:
            self.add("warn", "anim-without-say", "data-anim is set but there is no data-say, so nothing animates.",
                     'Add data-say="narration sentence" to the same element, or remove data-anim.')
        if "data-caption" in a:
            if not (a.get("data-say") or "").strip():
                self.add("error", "caption-without-say", "data-caption is set but data-say (the narration) is missing.",
                         'Add data-say="narration written the way it should be read" to the same element. If the caption and the reading are the same, remove data-caption and keep only data-say.')
            elif len(sentences(a["data-say"])) != len(sentences(a["data-caption"] or "")):
                self.add("error", "caption-mismatch", "data-say has %d sentence(s) but data-caption has %d, so captions cannot be paired sentence by sentence."
                         % (len(sentences(a["data-say"])), len(sentences(a["data-caption"] or ""))),
                         "Write data-say and data-caption with the same number of sentences in the same order (the same number of 。 marks).")
        if self.in_slide() and tag != "section" and ("data-say" in a or "voice" in cls):
            self.slides[-1]["cues"] += 1
            say_val = (a.get("data-say") or "").strip()
            sents = sentences(say_val) if say_val else []
            if sents and "…" not in say_val:
                c0 = re.sub(r"[、。！？!?.・,\s]", "", sents[0])
                if ("kicker" in cls and say_val.endswith(("、", ","))) or (len(sents) > 1 and 0 < len(c0) <= 4):
                    self.add("warn", "short-sentence", 'The narration starts with a very short fragment ("%s"), which flashes captions briefly and can destabilise TTS.' % sents[0],
                             'Join short lead-in fragments with the main sentence (for example, write "一つ目は、…" with a comma instead of "一つ目。…", and put the opening sentence on <h1> rather than a separate data-say on .kicker).')
            sym_m = re.search(r"[◎○◯△▲×✕]", say_val)
            if sym_m:
                self.add("warn", "say-symbol", 'data-say contains a symbol ("%s") that speech engines may skip or misread.' % sym_m.group(0),
                         "Spell out symbols in data-say (for example, 二重丸, 丸, 三角, バツ) and keep ◎ / ○ / △ / × in data-caption.")
        m = re.search(r"font-size\s*:\s*(\d+(?:\.\d+)?)px", a.get("style") or "")
        floor = 14 if (self.deck_dense or (self.slides and "dense" in self.slides[-1]["cls"])) else 22
        if m and float(m.group(1)) < floor and not any(e["tag"] == "svg" for e in self.stack) and tag != "svg":
            self.add("error", "small-text", "font-size: %spx is too small (minimum %dpx)." % (m.group(1), floor), check.HINTS["small-text"])
        for k in ("src", "href", "xlink:href"):
            if tag in EXTERNAL_TAGS and re.match(r"\s*(https?:)?//", a.get(k) or ""):
                self.add("error", "external", "<%s> loads an external URL (it will not show when the deck is opened offline)." % tag, NO_EXTERNAL)
        if tag not in VOID:
            self.stack.append({"tag": tag, "line": line, "cls": cls, "kids": 0, "text": ""})

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1]["tag"] == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False
            return
        if tag in VOID:
            return
        idx = next((k for k in range(len(self.stack) - 1, -1, -1) if self.stack[k]["tag"] == tag), None)
        if idx is None:
            self.add("error", "unmatched-close", "</%s> has no matching opening tag." % tag,
                     "Remove the extra </%s>, or add the missing <%s>." % (tag, tag))
            return
        for e in self.stack[idx + 1:]:
            if e["tag"] not in OPTIONAL_END:
                self.add("error", "unclosed", "<%s> (line %d) is still open when </%s> appears." % (e["tag"], e["line"], tag),
                         "Add </%s>." % e["tag"], line=e["line"])
        e = self.stack[idx]
        del self.stack[idx:]
        if self.stack:
            self.stack[-1]["text"] += e["text"]
        self.measure(e)

    def measure(self, e):
        n = len(re.sub(r"\s+", "", e["text"]))
        tag, cls = e["tag"], e["cls"]
        if self.deck_dense or (self.slides and "dense" in self.slides[-1]["cls"]):
            return  # dense slides have no item-count guideline; the rendered check catches real overflow
        if tag in ("ul", "ol") and "flow" not in cls and e["kids"] > 5 and not any(x["tag"] in ("li", "td") or "box" in x["cls"] or "card" in x["cls"] for x in self.stack):
            self.add("warn", "many-items", "The list has %d items (4 fit comfortably, 5 at most)." % e["kids"],
                     "Cut items or split the slide in two. For an information-dense business document, add density: dense to the settings.", line=e["line"])
        if tag == "ol" and "flow" in cls and e["kids"] > 4:
            self.add("warn", "many-items", "The flow has %d steps (3 or 4 fit)." % e["kids"], "Merge steps or split the slide in two.", line=e["line"])
        if "cols" in cls and e["kids"] > 3:
            self.add("warn", "many-items", "There are %d columns (2 or 3 fit)." % e["kids"], "Use at most 3 columns, or split the slide in two.", line=e["line"])
        if tag == "tbody" and e["kids"] > 5:
            self.add("warn", "many-items", "The table has %d rows (up to 4 fit comfortably)." % e["kids"], "Cut rows or split the slide in two.", line=e["line"])
        if tag == "h1" and n > 28:
            self.add("warn", "long-text", "The cover heading is %d characters (aim for 2 lines, 24 characters)." % n,
                     'Shorten it and move the rest to <p class="sub"> or to the narration.', line=e["line"])
        if tag == "h2" and n > 22:
            self.add("warn", "long-text", "The heading is %d characters (about 20 fit on one line)." % n, "Shorten the heading.", line=e["line"])

    def handle_data(self, data):
        if self.in_style or not data.strip():
            return
        if not self.in_slide():
            self.add("error", "outside", 'Text is outside any slide: "%s"' % data.strip()[:20], INSIDE_SLIDES)
        elif self.stack:
            self.stack[-1]["text"] += data

    def finish(self):
        for e in self.stack:
            if e["tag"] not in OPTIONAL_END:
                self.issues.append({"line": e["line"], "type": "unclosed", "level": "error", "slide": 0,
                                    "msg": "<%s> is never closed." % e["tag"], "hint": "Add </%s>." % e["tag"]})
        for k, s in enumerate(self.slides, 1):
            if s["cues"] == 0:
                self.issues.append({"line": s["line"], "slide": k, "type": "no-narration", "level": "error",
                                    "msg": "This slide has no narration.", "hint": check.HINTS["no-narration"]})
        if self.slides and "title" not in self.slides[0]["cls"]:
            self.issues.append({"line": self.slides[0]["line"], "slide": 1, "type": "no-title", "level": "warn",
                                "msg": "The first slide is not a cover slide.",
                                "hint": 'Make slide 1 <section class="slide title"> with the deck title in an <h1>.'})
        self.issues.sort(key=lambda i: i["line"])
        return self.issues


def parse_source(text):
    """Return (settings, custom CSS, slide markup, problems with the settings)."""
    meta = {"title": "", "theme": "light", "lang": "ja", "density": "normal", "footer": None}
    problems = []
    m = HEADER.match(text)
    if m and re.search(r"^\s*(title|theme|lang|density|footer)\s*:", m.group(1), re.M):
        for line in m.group(1).splitlines():
            k, sep, v = line.partition(":")
            if sep and k.strip().lower() in meta:
                meta[k.strip().lower()] = v.strip()
        body = text[m.end():]
    else:
        body = text
        problems.append({"line": 1, "slide": 0, "type": "no-header", "level": "error", "msg": "The source does not start with the settings comment.",
                         "hint": "Start the file with these four lines:\n        <!--\n        title: the deck title\n        theme: light\n        -->"})
    if m and not meta["title"] and not problems:
        problems.append({"line": 1, "slide": 0, "type": "no-title-setting", "level": "error", "msg": "The settings comment has no title.",
                         "hint": 'Add a line "title: the deck title".'})
    if meta["density"] not in ("normal", "dense"):
        problems.append({"line": 1, "slide": 0, "type": "unknown-density", "level": "error", "msg": 'density "%s" does not exist.' % meta["density"],
                         "hint": "Use density: dense (information-dense business documents), or delete the line (standard)."})
    if meta["theme"] not in THEMES:
        problems.append({"line": 1, "slide": 0, "type": "unknown-theme", "level": "error", "msg": 'Theme "%s" does not exist.' % meta["theme"],
                         "hint": near(meta["theme"], THEMES) + "Available themes: " + ", ".join(THEMES) + "."})
    styles = re.findall(r"<style\b[^>]*>(.*?)</style>", body, re.S)
    slides = re.sub(r"<style\b[^>]*>.*?</style>\s*", "", body, flags=re.S).strip()
    for bad in ("SLIDES:START", "SLIDES:END", "ENGINE JS"):
        if bad in slides:
            problems.append({"line": text[:text.index(bad)].count("\n") + 1, "slide": 0, "type": "whole-page", "level": "error",
                             "msg": 'The source contains "%s" (a whole page or the template was pasted in).' % bad,
                             "hint": 'The source holds only the settings comment and <section class="slide"> elements. Do not write <html>, <body> or any part of the template.'})
            break
    return meta, "\n".join(s.strip() for s in styles), slides, problems


def lint(text):
    meta, css, slides, problems = parse_source(text)
    custom = set(re.findall(r"\.([A-Za-z_][\w-]*)", css))
    p = Lint(custom, dense=meta["density"] == "dense")
    p.feed(text)
    p.close()
    issues = problems + p.finish()
    if not p.slides and not any(i["type"] == "whole-page" for i in issues):
        issues.append({"line": 1, "slide": 0, "type": "no-slides", "level": "error", "msg": "There are no slides.",
                       "hint": 'Add <section class="slide"> ... </section> elements.'})
    return meta, css, slides, issues, [s["line"] for s in p.slides]


def assemble(meta, css, slides, out_path):
    t = TEMPLATE.read_text(encoding="utf-8")
    extra = ' translate="no"' + (' data-density="dense"' if meta.get("density") == "dense" else "") + (' data-footer="%s"' % html.escape(meta["footer"]) if meta.get("footer") is not None else "")
    t = re.sub(r'<html lang="[^"]*" data-theme="[^"]*"[^>]*>', lambda _: '<html lang="%s" data-theme="%s"%s>' % (html.escape(meta["lang"]), meta["theme"], extra), t, count=1)
    t = re.sub(r"<title>.*?</title>", lambda _: "<title>%s</title>" % html.escape(meta["title"], quote=False), t, count=1, flags=re.S)
    t, k = REGION.subn(lambda m: m.group(1) + "\n" + slides + "\n\n" + m.group(2), t, count=1)
    if k != 1:
        fail("The template is damaged: " + str(TEMPLATE))
    if css:
        t = t.replace("</head>", '<style id="custom">\n%s\n</style>\n</head>' % css, 1)
    if out_path.exists():
        try:
            vm = VOICE_BLOCK.search(out_path.read_text(encoding="utf-8"))
            if vm and ENGINE_MARKER in t:
                t = t.replace(ENGINE_MARKER, vm.group(0) + ENGINE_MARKER, 1)
        except OSError:
            pass
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(t, encoding="utf-8")


def extract(deck_path, out_path):
    t = read_source(deck_path)
    m = REGION.search(t)
    if not m:
        fail("This HTML was not built by this skill: " + str(deck_path))
    body = t[m.end(1):m.start(2)].strip()
    title = html.unescape(re.search(r"<title>(.*?)</title>", t, re.S).group(1).strip())
    hm = re.search(r'<html lang="([^"]*)" data-theme="([^"]*)"([^>]*)>', t)
    lang, theme, rest = (hm.group(1), hm.group(2), hm.group(3)) if hm else ("ja", "light", "")
    fm = re.search(r'data-footer="([^"]*)"', rest)
    cm = CUSTOM.search(t)
    src = "<!--\ntitle: %s\ntheme: %s\n%s%s%s-->\n" % (title, theme, "" if lang == "ja" else "lang: %s\n" % lang,
                                                    "density: dense\n" if 'data-density="dense"' in rest else "",
                                                    "footer: %s\n" % html.unescape(fm.group(1)) if fm else "")
    if cm:
        src += "<style>\n%s\n</style>\n" % cm.group(1).strip()
    out_path.write_text(src + "\n" + body + "\n", encoding="utf-8")
    print("Source extracted: %s" % out_path)


def main():
    check.setup_console()
    ap = argparse.ArgumentParser(description="Lint a slide source (.slides.html) and assemble the finished HTML deck")
    ap.add_argument("source", help="the source (.slides.html); with --extract, a built deck")
    ap.add_argument("-o", "--out", help="output path (default: <name>.html next to the source)")
    ap.add_argument("--shots", metavar="DIR", help="folder to save screenshots in")
    ap.add_argument("--no-render", "--no-check", dest="no_render", action="store_true", help="skip the browser check (lint and assemble only)")
    ap.add_argument("--extract", action="store_true", help="recover the source from a built deck")
    a = ap.parse_args()

    src = pathlib.Path(a.source).resolve()
    if not src.exists():
        fail("File not found: " + str(src))
    if a.out:
        out = pathlib.Path(a.out).resolve()
    elif a.extract:
        out = src.with_name(src.stem + ".slides.html")
    else:
        name = src.name[:-len(".slides.html")] if src.name.endswith(".slides.html") else src.stem + ".out"
        out = src.with_name(name + ".html")
    if out.exists() and out.samefile(src):
        fail("The output path is the same as the source. Pass -o with a different name.")

    if a.extract:
        if out.exists() and not a.out:
            fail("%s already exists. Pass -o to overwrite it explicitly." % out)
        extract(src, out)
        return 0

    # 1. source lint
    meta, css, slides, issues, lines = lint(read_source(src))
    if any(i["level"] == "error" for i in issues):
        print("Source lint: %s" % src.name)
        check.print_issues(issues)
        print("(The deck was NOT built.)")
        return 1

    # 2. assemble
    assemble(meta, css, slides, out)
    print("Built: %s (%d slides, theme %s)" % (out, len(lines), meta["theme"]), flush=True)
    if a.no_render:
        check.print_issues(issues)
        print("(The rendered check was skipped, so overflow has NOT been verified.)")
        return 0

    # 3. rendered check
    try:
        rep = check.inspect(out)
    except check.CheckError as e:
        check.print_issues(issues)
        print("The rendered check could not run: %s" % e)
        print("The deck was built, but overflow has NOT been verified. Tell the user so.")
        return 2
    bad = check.report(rep, lines=lines, extra=issues)
    if a.shots:
        try:
            outdir, dense = check.shots(rep, a.shots)
        except check.CheckError as e:
            print("Screenshots could not be saved: %s" % e)
            return 1 if bad else 2
        print("Screenshots: %s (slide-01.png ..., plus phone views mobile-portrait.png / mobile-landscape.png showing slide %d)" % (outdir, dense))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
