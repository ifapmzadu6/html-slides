#!/usr/bin/env python3
"""Generate narration audio on this computer only and embed it in a built deck.
The narration text never leaves the machine.

Usage:
  python3 add_voice.py deck.html                 # find a running local speech engine automatically
  python3 add_voice.py deck.html --list          # list the available voices
  python3 add_voice.py deck.html --speaker 13    # choose a voice (a number from --list)
  python3 add_voice.py deck.html --speed 1.1     # speaking rate
  python3 add_voice.py deck.html --engine kokoro --speaker jf_alpha  # use local Kokoro-82M
  python3 add_voice.py deck.html --engine qwen3 --speaker Ono_Anna   # use local Qwen3-TTS (Apple Silicon MLX)
  python3 add_voice.py deck.html --engine say    # use the built-in macOS voice (low quality)
  python3 add_voice.py deck.html --remove        # remove the embedded audio

Speech engines (all run on this computer):
  voicevox : VOICEVOX, AivisSpeech or another VOICEVOX-compatible app (Japanese voices). The app must be running.
             Connections are limited to 127.0.0.1 (this computer); any other address is refused.
  kokoro   : Kokoro-82M, via a local Kokoro-FastAPI server (127.0.0.1:8880) or the Python `kokoro` package.
  qwen3    : Qwen3-TTS via `mlx-audio` on Apple Silicon (e.g. mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16).
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
import unicodedata
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
QWEN3_DEFAULT_MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16"
QWEN3_ALIGNER_MODEL = "mlx-community/Qwen3-ForcedAligner-0.6B-8bit"
QWEN3_DEFAULT_VOICE = "Ono_Anna"
QWEN3_DEFAULT_INSTRUCT = (
    "あなたはプロのナレーターとして、パワーポイント資料のプレゼンテーション発表を行っています。"
    "聴衆にスライドの内容がすっと伝わるよう、最初から最後まで一定の速度と落ち着いた声のトーンを保ち、"
    "過剰な感情表現やため息を入れず、自然で明瞭な話し方で読み上げてください。"
)
QWEN3_VOICES = [
    ("Ono_Anna", "Japanese (female)"),
    ("Vivian", "Chinese (female)"),
    ("Serena", "Chinese (female)"),
    ("Uncle_Fu", "Chinese (male)"),
    ("Dylan", "Chinese Beijing (male)"),
    ("Eric", "Chinese Sichuan (male)"),
    ("Ryan", "English (male)"),
    ("Aiden", "English (male)"),
    ("Sohee", "Korean (female)"),
]
QWEN3_VOICE_LANGS = {
    "Ono_Anna": "ja",
    "Ryan": "en",
    "Aiden": "en",
    "Sohee": "ko",
    "Vivian": "zh",
    "Serena": "zh",
    "Uncle_Fu": "zh",
    "Dylan": "zh",
    "Eric": "zh",
}
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
            if isinstance(data, dict) and isinstance(data.get("voices"), list):
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


def clean_speech(samples, sample_rate=24000, threshold=0.004, max_pause=0.45, keep_pause=0.24):
    """Trim leading/trailing silence and shorten abnormally long internal pauses without clipping voiceless consonants or endings."""
    win = max(1, int(sample_rate * 0.02))
    n_frames = len(samples) // win
    if n_frames < 3:
        return samples
    # Compute per-frame RMS and dilate by 2 frames (±40ms) so voiceless consonants (つ, っ, す, etc.) are preserved.
    rms = []
    for i in range(n_frames):
        chunk = samples[i * win : (i + 1) * win]
        rms.append((sum(x * x for x in chunk) / win) ** 0.5)
    active = [
        any(rms[j] >= threshold for j in range(max(0, i - 2), min(n_frames, i + 3)))
        for i in range(n_frames)
    ]
    if not any(active):
        return samples
    # Keep 80ms (4 frames) before onset and 200ms (10 frames) after offset so trailing devoiced 'す/ます/です' is never clipped.
    first = max(0, active.index(True) - 4)
    last = min(n_frames - 1, n_frames - 1 - active[::-1].index(True) + 10)
    max_q = max(1, int(max_pause / 0.02))
    keep_q = max(1, int(keep_pause / 0.02))
    fade = min(win // 2, int(sample_rate * 0.01))
    out = []
    i = first
    while i <= last:
        if active[i]:
            out.extend(samples[i * win : (i + 1) * win])
            i += 1
        else:
            j = i
            while j <= last and not active[j]:
                j += 1
            run = j - i
            if run > max_q:
                head = keep_q // 2
                tail = keep_q - head
                part = list(samples[i * win : (i + head) * win]) + list(samples[(j - tail) * win : j * win])
                # Smooth any splice discontinuity with a short crossfade.
                mid = head * win
                for k in range(min(fade, mid, len(part) - mid)):
                    alpha = k / fade
                    part[mid - fade + k] *= 1.0 - alpha
                    part[mid + k] *= alpha
                out.extend(part)
            else:
                out.extend(samples[i * win : j * win])
            i = j
    # Soft fade-in / fade-out at clip boundaries.
    for k in range(min(fade, len(out) // 2)):
        g = k / fade
        out[k] *= g
        out[-1 - k] *= g
    return out


def pcm_to_wav(samples, sample_rate=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        pcm = [max(-32768, min(32767, int(s * 32767.0))) for s in samples]
        wf.writeframes(struct.pack("<%dh" % len(pcm), *pcm))
    return buf.getvalue()


def kokoro_py_synth(text, voice, speed, pipelines):
    from kokoro import KPipeline  # noqa: PLC0415

    lang = kokoro_lang_code(voice)
    if lang not in pipelines:
        pipelines[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")
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
    return pcm_to_wav(samples, 24000)


def qwen3_available():
    return importlib.util.find_spec("mlx_audio") is not None


def qwen3_lang_code(voice):
    return QWEN3_VOICE_LANGS.get(voice, "auto")


QWEN3_READING_FIXES = [
    ("左右キー", "さゆうキー"),
    ("左右の", "さゆうの"),
    ("上下の", "じょうげの"),
    ("日本語話者", "日本語の声"),
    ("話者", "わしゃ"),
]


def _prep_qwen3_text(s):
    s = re.sub(r"[、,]+\s*$", "", s.strip()).replace("、", " ")
    for k, v in QWEN3_READING_FIXES:
        s = s.replace(k, v)
    if s and s[-1] not in "。！？!?.":
        s += "。"
    return s


def qwen3_synth(text, voice, speed, model_id, cache, instruct=None, temperature=None):
    import numpy as np  # noqa: PLC0415
    from mlx_audio.tts.utils import load_model  # noqa: PLC0415

    if "model" not in cache:
        cache["model"] = load_model(model_id)
    results = list(
        cache["model"].generate(
            text=_prep_qwen3_text(text),
            voice=voice,
            instruct=instruct or None,
            temperature=temperature,
            lang_code=qwen3_lang_code(voice),
            speed=speed,
        )
    )
    if not results:
        raise ValueError("Qwen3-TTS produced empty audio")
    audio = np.concatenate([np.asarray(r.audio) for r in results])
    if len(audio) == 0:
        raise ValueError("Qwen3-TTS produced empty audio")
    sr = getattr(results[0], "sample_rate", 24000) or 24000
    cleaned = clean_speech(audio.tolist(), int(sr))
    return pcm_to_wav(cleaned, int(sr))


QWEN3_ALIGNER_LANGS = {"ja": "Japanese", "en": "English", "ko": "Korean", "zh": "Chinese"}


def _norm_alnum(s):
    return "".join(c for c in s if unicodedata.category(c)[0] in ("L", "N"))


def _min_energy_cut(samples, sr, t_left, t_right):
    """Find the lowest-energy sample index after sentence end (t_left) and before next sentence start (t_right)."""
    win = max(1, int(sr * 0.01))
    gap = t_right - t_left
    # Bias toward the end of the gap so trailing devoiced syllables ('〜です', '〜ます') of the previous sentence are kept intact.
    start_t = t_left + min(0.12, max(0.0, gap * 0.45))
    end_t = max(start_t, t_right - 0.02)
    a = max(0, int(start_t * sr))
    b = min(len(samples) - win, int(end_t * sr))
    if b <= a:
        return max(0, min(len(samples), int(max(t_left, t_right - 0.02) * sr)))
    best_i, best_e = a, float("inf")
    step = max(1, win // 2)
    for idx in range(a, b + 1, step):
        chunk = samples[idx : idx + win]
        e = sum(x * x for x in chunk)
        if e < best_e:
            best_e, best_i = e, idx + win // 2
    return best_i


def qwen3_batch_synth(texts, voice, speed, model_id, cache, tmp, instruct=None, temperature=None, all_texts=None):
    """Synthesize sentences in multi-sentence batches for prosodic consistency, then slice with Qwen3-ForcedAligner."""
    import numpy as np  # noqa: PLC0415
    from mlx_audio.stt.utils import load_model as load_stt_model  # noqa: PLC0415
    from mlx_audio.tts.utils import load_model as load_tts_model  # noqa: PLC0415

    if "model" not in cache:
        cache["model"] = load_tts_model(model_id)
    if "aligner" not in cache:
        try:
            cache["aligner"] = load_stt_model(QWEN3_ALIGNER_MODEL)
        except Exception:
            cache["aligner"] = None

    # If only 1 sentence needs generation in a multi-sentence deck, include 1-2 neighbouring sentences as prosodic context.
    synth_list = list(texts)
    if len(synth_list) == 1 and all_texts and len(all_texts) > 1 and synth_list[0] in all_texts:
        pos = all_texts.index(synth_list[0])
        lo = max(0, pos - 1)
        hi = min(len(all_texts), lo + 3)
        synth_list = list(all_texts[lo:hi])

    # Group into batches of up to 200 sentences / ~5000 chars (~10+ min of audio at 12 Hz with max_tokens=8192)
    # so even long multi-slide decks are synthesized in a single continuous take.
    batches = []
    cur_b, cur_chars = [], 0
    for t in synth_list:
        if cur_b and (len(cur_b) >= 200 or cur_chars + len(t) > 5000):
            batches.append(cur_b)
            cur_b, cur_chars = [], 0
        cur_b.append(t)
        cur_chars += len(t)
    if cur_b:
        batches.append(cur_b)

    out = {}
    lang = qwen3_lang_code(voice)
    align_lang = QWEN3_ALIGNER_LANGS.get(lang, "Japanese")
    for batch in batches:
        if len(batch) == 1 or cache["aligner"] is None:
            for t in batch:
                out[t] = qwen3_synth(t, voice, speed, model_id, cache, instruct, temperature)
            continue
        # Strip '、' for smoother TTS phrasing and join with '\n' (while split_pattern='') so the model leaves a clean pause between clips.
        spoken_batch = [_prep_qwen3_text(s) for s in batch]
        joined = "\n".join(spoken_batch)
        try:
            results = list(
                cache["model"].generate(
                    text=joined,
                    voice=voice,
                    instruct=instruct or None,
                    temperature=temperature,
                    lang_code=lang,
                    speed=speed,
                    split_pattern="",
                    max_tokens=8192,
                )
            )
            if not results:
                raise ValueError("empty batch audio")
            audio = np.concatenate([np.asarray(r.audio) for r in results])
            sr = int(getattr(results[0], "sample_rate", 24000) or 24000)
            bwav = tmp / "batch.wav"
            bwav.write_bytes(pcm_to_wav(audio.tolist(), sr))
            ares = cache["aligner"].generate(audio=str(bwav), text=joined, language=align_lang)
            items = getattr(ares, "items", None) or []
            if not items:
                raise ValueError("no alignment items")
            spans = []
            idx = 0
            for s in batch:
                target = max(1, len(_norm_alnum(s)))
                cur_len = 0
                start_i = min(idx, len(items) - 1)
                while idx < len(items) and cur_len < target:
                    cur_len += len(_norm_alnum(items[idx].text))
                    idx += 1
                end_i = max(start_i, min(idx - 1, len(items) - 1))
                spans.append((items[start_i].start_time, items[end_i].end_time))
            samples_list = audio.tolist()
            cuts = [max(0, int((spans[0][0] - 0.08) * sr))]
            for k in range(len(batch) - 1):
                cuts.append(_min_energy_cut(samples_list, sr, spans[k][1], spans[k + 1][0]))
            cuts.append(min(len(samples_list), int((spans[-1][1] + 0.35) * sr)))
            for k, s in enumerate(batch):
                i0, i1 = cuts[k], max(cuts[k] + 1, cuts[k + 1])
                seg = clean_speech(samples_list[i0:i1], sr, threshold=0.004)
                if not seg:
                    raise ValueError("empty segment after alignment")
                out[s] = pcm_to_wav(seg, sr)
        except Exception:
            for t in batch:
                out[t] = qwen3_synth(t, voice, speed, model_id, cache, instruct, temperature)
    return out


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
    ap.add_argument("--engine", choices=["auto", "voicevox", "kokoro", "qwen3", "say"], default="auto")
    ap.add_argument("--url", help="address of a VOICEVOX or Kokoro-FastAPI engine (127.0.0.1 only)")
    ap.add_argument("--speaker", help="voice: a number for voicevox, a voice name for kokoro, qwen3 or say")
    ap.add_argument("--model", default=QWEN3_DEFAULT_MODEL, help="Hugging Face model ID for qwen3")
    ap.add_argument("--instruct", default=QWEN3_DEFAULT_INSTRUCT, help="style/emotion instruction for qwen3 (empty string to disable)")
    ap.add_argument("--temperature", type=float, help="sampling temperature for qwen3 (lower is calmer)")
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
    qwen3_ok = (not base and not kokoro_base and not kokoro_py and not a.url and a.engine in ("auto", "qwen3") and qwen3_available())
    if base:
        engine = "voicevox"
    elif kokoro_base:
        engine = "kokoro-api"
    elif kokoro_py:
        engine = "kokoro-py"
    elif qwen3_ok:
        engine = "qwen3"
    elif a.engine == "say":
        engine = "say"
    else:
        engine = None
    if not engine:
        print("No local speech engine was found.")
        print("  Start VOICEVOX / AivisSpeech (127.0.0.1:50021/10101), Kokoro-FastAPI (127.0.0.1:8880),")
        print('  or install Python `kokoro` ("misaki[ja]") or `mlx-audio` (for Qwen3-TTS on Apple Silicon).')
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
        if not speakers:
            print("ERROR: Kokoro reported no voices installed.")
            return 2
        if a.list:
            print("Engine: %s" % kokoro_base)
            for vid, desc in speakers:
                print("  %s" % vid)
            return 0
        label = a.speaker or (KOKORO_DEFAULT_VOICE if any(v == KOKORO_DEFAULT_VOICE for v, _ in speakers) else speakers[0][0])
        if label not in dict(speakers):
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
    elif engine == "qwen3":
        if a.list:
            print("Engine: qwen3 (%s)" % a.model)
            for vid, desc in QWEN3_VOICES:
                print("  %-15s %s" % (vid, desc))
            return 0
        label = a.speaker or QWEN3_DEFAULT_VOICE
        key = "qwen3:%s:%s:%s:%s" % (a.model, label, a.instruct or "", "" if a.temperature is None else a.temperature)
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
    qwen3_cache = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        qwen3_pre = (
            qwen3_batch_synth(todo, label, a.speed, a.model, qwen3_cache, tmp, a.instruct, a.temperature, all_texts=texts)
            if engine == "qwen3" and todo
            else {}
        )
        for n, t in enumerate(todo, 1):
            try:
                if engine == "voicevox":
                    raw, ext = voicevox_synth(base, t, sid, a.speed), ".wav"
                elif engine == "kokoro-api":
                    raw, ext = kokoro_api_synth(kokoro_base, t, label, a.speed), ".wav"
                elif engine == "kokoro-py":
                    raw, ext = kokoro_py_synth(t, label, a.speed, kokoro_pipelines), ".wav"
                elif engine == "qwen3":
                    raw, ext = qwen3_pre[t], ".wav"
                else:
                    raw, ext = say_synth(t, label, a.speed, tmp)
            except (urllib.error.URLError, OSError, subprocess.CalledProcessError, ValueError, RuntimeError) as e:
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
