#!/usr/bin/env python3
"""Generate narration audio on this computer only and embed it in a built deck.
The narration text never leaves the machine.

Usage:
  python3 add_voice.py deck.html                 # find a running local speech engine automatically
  python3 add_voice.py deck.html --list          # list the available voices
  python3 add_voice.py deck.html --speaker 13    # choose a voice (a number from --list)
  python3 add_voice.py deck.html --speed 1.1     # speaking rate
  python3 add_voice.py deck.html --engine kokoro --speaker jf_alpha  # use local Kokoro-82M
  python3 add_voice.py deck.html --engine say    # use the built-in macOS voice (low quality)
  python3 add_voice.py deck.html --remove        # remove the embedded audio

Speech engines (all run on this computer):
  voicevox : VOICEVOX, AivisSpeech or another VOICEVOX-compatible app (Japanese voices). The app must be running.
             Connections are limited to 127.0.0.1 (this computer); any other address is refused.
  kokoro   : Kokoro-82M, via a local Kokoro-FastAPI server (127.0.0.1:8880) or the Python `kokoro` package.
  say      : the speech built into macOS. Nothing to install, but it sounds robotic.

- Each sentence of the narration becomes one clip, written into deck.html as a data URI (still one file).
- Rerun after changing the narration. Sentences that did not change are not regenerated.
- The list of sentences comes from the player itself, so Chrome or Edge is required (as for check.py).
- With ffmpeg (or afconvert on macOS) the audio is compressed. With neither, it is stored uncompressed and the file is large.
"""
import argparse
import base64
import html
import importlib.util
import io
import json
import pathlib
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import wave

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from check import CheckError, find_browser, run, setup_console  # noqa: E402

BLOCK = re.compile(r"<!-- VOICE:START -->.*?<!-- VOICE:END -->\n?", re.S)
ENGINE = "<script>\n/* ===== ENGINE JS"
LOCAL_PORTS = [10101, 50021]  # AivisSpeech, VOICEVOX
KOKORO_PORTS = [8880]  # Kokoro-FastAPI
KOKORO_DEFAULT_VOICE = "jf_alpha"
KOKORO_PY_VOICES = [
    ("jf_alpha", "Japanese (female)"),
    ("jf_gongitsune", "Japanese (female)"),
    ("jf_nezumi", "Japanese (female)"),
    ("jf_tebukuro", "Japanese (female)"),
    ("jm_kumo", "Japanese (male)"),
    ("af_heart", "American English (female)"),
    ("af_bella", "American English (female)"),
    ("am_adam", "American English (male)"),
    ("bf_emma", "British English (female)"),
    ("bm_george", "British English (male)"),
]
# Always connect straight to 127.0.0.1, ignoring any proxy settings, so the narration cannot leave the machine.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def local_url(url):
    host = urllib.parse.urlparse(url).hostname
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("ERROR: %s is not this computer. Only 127.0.0.1 is allowed, so that the narration is never sent elsewhere." % url)
    return url.rstrip("/")


def http(url, data=None, timeout=120):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST" if data is not None else "GET")
    with OPENER.open(req, timeout=timeout) as r:
        return r.read()


def find_voicevox(url):
    for u in ([local_url(url)] if url else ["http://127.0.0.1:%d" % p for p in LOCAL_PORTS]):
        try:
            http(u + "/version", timeout=2)
            return u
        except (urllib.error.URLError, OSError):
            continue
    return None


def voicevox_speakers(base):
    out = []
    for sp in json.loads(http(base + "/speakers")):
        for st in sp.get("styles", []):
            out.append((st["id"], "%s（%s）" % (sp["name"], st["name"])))
    return out


def voicevox_synth(base, text, speaker, speed):
    q = json.loads(http(base + "/audio_query?" + urllib.parse.urlencode({"text": text, "speaker": speaker}), data=b""))
    q["speedScale"] = speed
    q["prePhonemeLength"] = 0.05
    q["postPhonemeLength"] = 0.1
    return http(base + "/synthesis?" + urllib.parse.urlencode({"speaker": speaker}), data=json.dumps(q).encode("utf-8"))


def find_kokoro_api(url):
    for u in ([local_url(url)] if url else ["http://127.0.0.1:%d" % p for p in KOKORO_PORTS]):
        try:
            data = json.loads(http(u + "/v1/audio/voices", timeout=2))
            if isinstance(data, dict) and "voices" in data:
                return u
        except (urllib.error.URLError, OSError, ValueError):
            continue
    return None


def kokoro_api_voices(base):
    return [(v, v) for v in json.loads(http(base + "/v1/audio/voices")).get("voices", [])]


def kokoro_api_synth(base, text, voice, speed):
    payload = json.dumps({
        "model": "kokoro",
        "input": text,
        "voice": voice,
        "speed": speed,
        "response_format": "wav",
    }).encode("utf-8")
    return http(base + "/v1/audio/speech", data=payload)


def kokoro_py_available():
    return importlib.util.find_spec("kokoro") is not None


def kokoro_lang_code(voice):
    # Kokoro voice IDs start with a language prefix: j (ja), a (en-US), b (en-GB), z (zh), etc.
    return voice[0] if voice and voice[0] in "jabzefhip" else "j"


def kokoro_py_synth(text, voice, speed, pipelines):
    from kokoro import KPipeline  # noqa: PLC0415

    lang = kokoro_lang_code(voice)
    if lang not in pipelines:
        pipelines[lang] = KPipeline(lang_code=lang)
    samples = []
    for _, _, audio in pipelines[lang](text, voice=voice, speed=speed):
        if audio is None:
            continue
        if hasattr(audio, "tolist"):
            samples.extend(audio.tolist())
        else:
            samples.extend(audio)
    if not samples:
        raise ValueError("Kokoro produced empty audio")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        pcm = [max(-32768, min(32767, int(s * 32767.0))) for s in samples]
        wf.writeframes(struct.pack("<%dh" % len(pcm), *pcm))
    return buf.getvalue()


def say_voices():
    r = subprocess.run(["say", "-v", "?"], capture_output=True, text=True)
    seen, out = set(), []
    for line in r.stdout.splitlines():
        m = re.match(r"(.+?)\s{2,}(\w+)\s+#", line)
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append((m.group(1), m.group(2)))
    return out


def say_synth(text, voice, speed, tmp):
    out = tmp / "say.aiff"
    cmd = ["say", "-o", str(out), "-r", str(int(190 * speed))]
    if voice:
        cmd += ["-v", voice]
    subprocess.run(cmd + ["--", text], check=True, capture_output=True)
    return out.read_bytes(), ".aiff"


def compress(raw, ext, tmp):
    """Return (bytes, mime). Without a compression tool the audio stays uncompressed."""
    src = tmp / ("in" + ext)
    src.write_bytes(raw)
    if shutil.which("ffmpeg"):
        dst = tmp / "out.mp3"
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-b:a", "48k", str(dst)], capture_output=True)
        if r.returncode == 0 and dst.exists():
            return dst.read_bytes(), "audio/mpeg"
    if shutil.which("afconvert"):
        dst = tmp / "out.m4a"
        r = subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "48000", "-c", "1", str(src), str(dst)], capture_output=True)
        if r.returncode == 0 and dst.exists():
            return dst.read_bytes(), "audio/mp4"
    if ext == ".wav":
        return raw, "audio/wav"
    raise SystemExit("ERROR: the audio could not be converted. Install ffmpeg.")


def main():
    setup_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("deck")
    ap.add_argument("--engine", choices=["auto", "voicevox", "kokoro", "say"], default="auto")
    ap.add_argument("--url", help="address of a VOICEVOX or Kokoro-FastAPI engine (127.0.0.1 only)")
    ap.add_argument("--speaker", help="voice: a number for voicevox, a voice name for kokoro or say")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--remove", action="store_true")
    a = ap.parse_args()

    deck = pathlib.Path(a.deck).resolve()
    src = deck.read_text(encoding="utf-8")
    if ENGINE not in src:
        print("ERROR: this HTML was not built by this skill.")
        return 2

    old = {}
    m = BLOCK.search(src)
    if m:
        j = re.search(r'<script type="application/json" id="voice-data">(.*?)</script>', m.group(0), re.S)
        if j:
            try:
                old = json.loads(j.group(1).replace("<\\/", "</"))
            except ValueError:
                old = {}
        src = BLOCK.sub("", src)
    if a.remove:
        deck.write_text(src, encoding="utf-8")
        print("Embedded audio removed.")
        return 0

    # --- choose the engine ---
    base = find_voicevox(a.url) if a.engine in ("auto", "voicevox") else None
    kokoro_base = find_kokoro_api(a.url) if (not base and a.engine in ("auto", "kokoro")) else None
    kokoro_py = (not base and not kokoro_base and not a.url and a.engine in ("auto", "kokoro") and kokoro_py_available())
    if base:
        engine = "voicevox"
    elif kokoro_base:
        engine = "kokoro-api"
    elif kokoro_py:
        engine = "kokoro-py"
    elif a.engine == "say":
        engine = "say"
    else:
        engine = None
    if not engine:
        print("No local speech engine was found.")
        print("  Start VOICEVOX / AivisSpeech (127.0.0.1:50021/10101), Kokoro-FastAPI (127.0.0.1:8880),")
        print('  or install the Python package (`pip install kokoro "misaki[ja]"`).')
        if platform.system() == "Darwin":
            print("  For a quick trial, --engine say uses the built-in macOS voice (it sounds robotic).")
        print("The HTML was not changed. Without embedded audio the deck still plays with the device voice.")
        return 2

    if engine == "voicevox":
        try:
            speakers = voicevox_speakers(base)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            print("ERROR: could not get the voice list from the speech engine (%s)." % e)
            return 2
        if not speakers:
            print("ERROR: the speech engine has no voices installed. Download a voice in the app.")
            return 2
        if a.list:
            print("Engine: %s" % base)
            for sid, name in speakers:
                print("  %s  %s" % (sid, name))
            return 0
        try:
            sid = int(a.speaker) if a.speaker else speakers[0][0]
        except ValueError:
            print("ERROR: --speaker takes a number shown by --list.")
            return 2
        label = dict(speakers).get(sid)
        if label is None:
            print("ERROR: there is no voice %s. Check with --list." % a.speaker)
            return 2
        key = "voicevox:%s" % sid
    elif engine == "kokoro-api":
        try:
            speakers = kokoro_api_voices(kokoro_base)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            print("ERROR: could not get the voice list from Kokoro (%s)." % e)
            return 2
        if a.list:
            print("Engine: %s" % kokoro_base)
            for vid, desc in speakers:
                print("  %s" % vid)
            return 0
        label = a.speaker or (KOKORO_DEFAULT_VOICE if any(v == KOKORO_DEFAULT_VOICE for v, _ in speakers) else speakers[0][0])
        if speakers and label not in dict(speakers):
            print("ERROR: there is no voice %s. Check with --list." % a.speaker)
            return 2
        key = "kokoro:%s" % label
    elif engine == "kokoro-py":
        if a.list:
            print("Engine: kokoro (Python)")
            for vid, desc in KOKORO_PY_VOICES:
                print("  %-15s %s" % (vid, desc))
            return 0
        label = a.speaker or KOKORO_DEFAULT_VOICE
        key = "kokoro:%s" % label
    else:
        if shutil.which("say") is None:
            print("ERROR: the say engine exists only on macOS.")
            return 2
        if a.list:
            for name, loc in say_voices():
                print("  %s  (%s)" % (name, loc))
            return 0
        label = a.speaker or "Kyoko"
        key = "say:%s" % label

    # --- get the narration sentences from the player ---
    browser = find_browser()
    if not browser:
        print("Chrome / Edge was not found. Set the CHROME environment variable to its path.")
        return 2
    try:
        r = run(browser, ["--window-size=1280,720", "--virtual-time-budget=5000", "--dump-dom", deck.as_uri() + "?check=1"])
    except CheckError as e:
        print("The narration could not be read: %s" % e)
        return 2
    rep = re.search(r'<pre id="check-report">(.*?)</pre>', r.stdout, re.S)
    if not rep:
        print("The narration could not be read. Make the deck pass check.py first.")
        return 2
    texts = json.loads(html.unescape(rep.group(1)))["texts"]

    reuse = old.get("clips", {}) if (old.get("voice"), old.get("speed")) == (key, a.speed) else {}
    clips = {t: reuse[t] for t in texts if t in reuse}
    todo = [t for t in texts if t not in clips]
    print("%d sentences, %d to generate, voice: %s (generated on this computer)" % (len(texts), len(todo), label))
    kokoro_pipelines = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        for n, t in enumerate(todo, 1):
            try:
                if engine == "voicevox":
                    raw, ext = voicevox_synth(base, t, sid, a.speed), ".wav"
                elif engine == "kokoro-api":
                    raw, ext = kokoro_api_synth(kokoro_base, t, label, a.speed), ".wav"
                elif engine == "kokoro-py":
                    raw, ext = kokoro_py_synth(t, label, a.speed, kokoro_pipelines), ".wav"
                else:
                    raw, ext = say_synth(t, label, a.speed, tmp)
            except (urllib.error.URLError, OSError, subprocess.CalledProcessError, ValueError) as e:
                print("Audio could not be generated: %s (%s)" % (t[:30], e))
                print("The HTML was not changed.")
                return 1
            data, mime = compress(raw, ext, tmp)
            clips[t] = "data:%s;base64,%s" % (mime, base64.b64encode(data).decode("ascii"))
            if n % 10 == 0:
                print("  %d / %d" % (n, len(todo)))

    data = json.dumps({"voice": key, "label": label, "speed": a.speed, "clips": {t: clips[t] for t in texts}}, ensure_ascii=False).replace("</", "<\\/")
    block = '<!-- VOICE:START -->\n<script type="application/json" id="voice-data">%s</script>\n<!-- VOICE:END -->\n' % data
    deck.write_text(src.replace(ENGINE, block + ENGINE, 1), encoding="utf-8")
    print("Audio embedded: %s (%.1f MB)" % (deck.name, deck.stat().st_size / 1e6))
    if engine == "voicevox":
        print("NOTE: VOICEVOX / AivisSpeech voices usually require a credit when the deck is published (for example \"VOICEVOX:%s\"). Check the terms of use of the voice you chose." % label.split("（")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
