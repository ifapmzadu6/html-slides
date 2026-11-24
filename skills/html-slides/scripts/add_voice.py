#!/usr/bin/env python3
"""Generate narration audio on this computer only and embed it in a built deck.
The narration text never leaves the machine.

Usage:
  python3 add_voice.py deck.html                 # find a running local speech engine automatically
  python3 add_voice.py deck.html --list          # list the available voices
  python3 add_voice.py deck.html --speaker 13    # choose a voice (a number from --list)
  python3 add_voice.py deck.html --speed 1.1     # speaking rate
  python3 add_voice.py deck.html --engine kokoro --speaker jf_alpha  # use local Kokoro-82M
  python3 add_voice.py deck.html --engine qwen3 --speaker Ono_Anna   # use local Qwen3-TTS (Windows or Apple Silicon)
  python3 add_voice.py deck.html --engine say    # use the built-in macOS voice (low quality)
  python3 add_voice.py deck.html --remove        # remove the embedded audio

Speech engines (all run on this computer):
  voicevox : VOICEVOX, AivisSpeech or another VOICEVOX-compatible app (Japanese voices). The app must be running.
             Connections are limited to 127.0.0.1 (this computer); any other address is refused.
  kokoro   : Kokoro-82M, via a local Kokoro-FastAPI server (127.0.0.1:8880) or the Python `kokoro` package.
  qwen3    : Qwen3-TTS via qwen-tts (PyTorch CPU/CUDA) on Windows or mlx-audio on Apple Silicon.
  say      : the speech built into macOS. Nothing to install, but it sounds robotic.

- Each sentence of the narration becomes one clip, written into deck.html as a data URI (still one file).
- Rerun after changing the narration. Sentences that did not change are not regenerated.
- The list of sentences comes from the player itself, so Chrome or Edge is required (as for check.py).
- With ffmpeg (or afconvert on macOS) the audio is compressed. With neither, it is stored uncompressed and the file is large.
"""
import argparse
import base64
import html
from http.client import HTTPException
import importlib.util
import io
import json
import math
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
from build import DeckHead, deck_lock, staged_html
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
QWEN3_DEFAULT_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"
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
    "Ono_Anna": "japanese",
    "Ryan": "english",
    "Aiden": "english",
    "Sohee": "korean",
    "Vivian": "chinese",
    "Serena": "chinese",
    "Uncle_Fu": "chinese",
    "Dylan": "chinese",
    "Eric": "chinese",
}
# Always connect straight to 127.0.0.1, ignoring any proxy settings, so the narration cannot leave the machine.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def local_url(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("ERROR: %s is not this computer. Only http(s)://127.0.0.1 is allowed, so that the narration is never sent elsewhere." % url)
    return url.rstrip("/")


def http(url, data=None, timeout=120):
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    with OPENER.open(req, timeout=timeout) as r:
        return r.read()


def find_voicevox(url):
    for u in ([local_url(url)] if url else ["http://127.0.0.1:%d" % p for p in LOCAL_PORTS]):
        try:
            ver = json.loads(http(u + "/version", timeout=2))
            if isinstance(ver, str) and ver.strip():
                return u
        except (urllib.error.URLError, HTTPException, OSError, ValueError):
            continue
    return None


def voicevox_speakers(base):
    data = json.loads(http(base + "/speakers"))
    if not isinstance(data, list):
        raise ValueError("unexpected /speakers response")
    out = []
    for sp in data:
        if not isinstance(sp, dict) or not isinstance(sp.get("name"), str):
            continue
        styles = sp.get("styles")
        if not isinstance(styles, list):
            continue
        for st in styles:
            if isinstance(st, dict) and "id" in st and isinstance(st.get("name"), str):
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
        except (urllib.error.URLError, HTTPException, OSError, ValueError):
            continue
    return None


def kokoro_api_voices(base):
    data = json.loads(http(base + "/v1/audio/voices"))
    if not isinstance(data, dict) or not isinstance(data.get("voices"), list):
        raise ValueError("unexpected /v1/audio/voices response")
    return [(v, v) for v in data["voices"] if isinstance(v, str) and v.strip()]


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
    v = (voice or "").strip()
    return v[0].lower() if v and v[0].lower() in "jabzefhip" else "j"


def clean_speech(samples, sample_rate=24000, threshold=0.0015, max_pause=0.45, keep_pause=0.24):
    """Trim leading/trailing silence and shorten abnormally long internal pauses without clipping voiceless consonants or endings."""
    samples = [x if math.isfinite(x) else 0.0 for x in samples]
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
    first_act = active.index(True)
    last_act = n_frames - 1 - active[::-1].index(True)
    first = max(0, first_act - 4)
    last = min(n_frames - 1, last_act + 10)
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
    if last == n_frames - 1 and len(samples) > n_frames * win:
        out.extend(samples[n_frames * win :])
    # Normalize active speech loudness to ~-20 dBFS (RMS 0.095) with peak headroom at 0.90 so all clips play at a uniform volume.
    if out:
        sq = [x * x for x in out if abs(x) >= threshold]
        act_rms = (sum(sq) / len(sq)) ** 0.5 if sq else 0.0
        peak = max(abs(x) for x in out)
        if act_rms > 1e-4 and peak > 1e-4:
            gain = min(3.5, max(0.3, 0.095 / act_rms), 0.90 / peak)
            out = [x * gain for x in out]
    # Soft fade-in / fade-out at clip boundaries, then ensure at least 160ms (8 frames) of trailing silence cushion.
    for k in range(min(fade, len(out) // 2)):
        g = k / fade
        out[k] *= g
        out[-1 - k] *= g
    tail_frames = last - last_act
    if tail_frames < 8:
        out.extend([0.0] * ((8 - tail_frames) * win))
    return out


def pcm_to_wav(samples, sample_rate=24000):
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        pcm = [0 if not math.isfinite(s) else max(-32768, min(32767, int(s * 32767.0))) for s in samples]
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
    package = "qwen_tts" if platform.system() == "Windows" else "mlx_audio"
    return importlib.util.find_spec(package) is not None


def qwen3_lang_code(voice, text=""):
    if text and re.search(r"[\u3040-\u30ff]", text):
        return "japanese"
    return QWEN3_VOICE_LANGS.get(voice, "auto")


QWEN3_SYMBOL_FIXES = [
    ("◎", "にじゅうまる"),
    ("○", "まる"),
    ("◯", "まる"),
    ("△", "さんかく"),
    ("×", "バツ"),
]
QWEN3_KANJI_FIXES = [
    ("二重丸", "にじゅうまる"),
    ("見積書", "みつもりしょ"),
    ("稟議", "りんぎ"),
    ("遅延", "ちえん"),
    ("未満", "みまん"),
    ("内訳", "うちわけ"),
    ("打刻", "だこく"),
    ("初年度", "しょねんど"),
    ("初期", "しょき"),
]
_TAGGER = False


def _get_tagger():
    global _TAGGER  # noqa: PLW0603
    if _TAGGER is False:
        try:
            import fugashi  # noqa: PLC0415

            _TAGGER = fugashi.Tagger()
        except Exception:
            _TAGGER = None
    return _TAGGER


JA_DIGITS = ("ゼロ", "いち", "に", "さん", "よん", "ご", "ろく", "なな", "はち", "きゅう")


def _ja_currency_group(n):
    """Write each place explicitly so the synthesizer can read it as a yen amount."""
    numerals = "〇一二三四五六七八九"
    parts = []
    for place, unit in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
        digit, n = divmod(n, place)
        if digit:
            parts.append(("" if digit == 1 and unit else numerals[digit]) + unit)
    return "".join(parts)


def _ja_num_units(m):
    n = int(m.group(0))
    if n < 10000 or n >= 10**12:
        return m.group(0)
    oku, rem = divmod(n, 100_000_000)
    man, rest = divmod(rem, 10_000)
    if m.string.startswith("円", m.end()):
        return "".join(_ja_currency_group(group) + unit for group, unit in ((oku, "億"), (man, "万"), (rest, ""))
                       if group)
    parts = []
    if oku:
        parts.append(f"{oku}億")
    if man:
        parts.append(f"{man}万")
    if rest:
        parts.append(str(rest))
    return "".join(parts)


def _ja_decimal(m):
    whole, fraction, day = m.groups()
    integer = "ゼロ" if whole in ("0", "０") else whole
    return integer + "てん" + "".join(JA_DIGITS[int(d)] for d in fraction) + ("にち" if day else "")


def _prep_qwen3_text(s, lang="japanese"):
    if lang != "japanese":
        return s.strip()

    s = re.sub(r"[、,]+\s*$", "", s.strip())
    # Remove thousands-separator commas inside numbers (e.g. 4,800 -> 4800) so TTS does not pause inside numbers.
    s = re.sub(r"(?<=\d)[,，](?=\d{3}(?!\d))", "", s)
    # Expand the sign before decimal conversion can replace the leading zero.
    # Limit hyphen interpretation to measured quantities, keeping dates and IDs intact.
    signs = {"-": "マイナス", "－": "マイナス", "−": "マイナス", "+": "プラス", "＋": "プラス", "±": "プラスマイナス"}
    s = re.sub(r"(?<![\dA-Za-zＡ-Ｚａ-ｚ_%％℃])(?<!\d度)([-－−+＋±])(?=[0-9０-９]+(?:[.．][0-9０-９]+)?[ \t]*[%％℃度])",
               lambda m: signs[m[1]], s)
    # Read each fractional digit, including zeros, even in a numeric-only cue.
    s = re.sub(r"(?<![A-Za-z_\d.．])([0-9０-９]+)[.．]([0-9０-９]+)(?![A-Za-z_\d]|[.．]\d)(日)?",
               _ja_decimal, s)
    # Always expand measurement symbols in Japanese narration, even for numeric-only cues like "25%" or "30℃".
    s = s.replace("±", "プラスマイナス").replace("%", "パーセント").replace("％", "パーセント").replace("℃", "度")
    if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", s):
        # A labeled identifier is a sequence of digits, including leading zeros.
        s = re.sub(r"(番号(?:は|が|：|:)?[ \t]*)([0-9０-９]+)(?![\dA-Za-z_.-])",
                   lambda m: m[1] + "、".join(JA_DIGITS[int(d)] for d in m[2]), s)
        # Only quantities with explicit units should acquire 万 or 億.
        s = re.sub(r"(?<![A-Za-z_\d.．])[1-9１-９]\d{4,11}(?=円|人|件|個|台|回|枚|冊|本|社|票|株|点|秒)",
                   _ja_num_units, s)
        # Convert 1-4 digit numbers before 円, 万円, 億円 (e.g. 3000円 -> 三千円, 4800万円 -> 四千八百万円) to explicit place-value kanji.
        s = re.sub(r"(?<![A-Za-z_\d.．])([1-9１-９][0-9０-９]{0,3})(?=(?:万|億)?円)",
                   lambda m: _ja_currency_group(int(m.group(1))), s)
        # Preserve the existing kanji decimal notation (e.g. 六・八万円).
        s = re.sub(r"([一二三四五六七八九十百千〇零])・([一二三四五六七八九〇零])", r"\1てん\2", s)
        s = re.sub(r"てん([〇零一二三四五六七八九0-9０-９])日", r"てん\1にち", s)
        s = re.sub(r"(?<![A-Za-zＡ-Ｚａ-ｚ_\d])[+＋](?=[0-9０-９])", "プラス", s)
        for k, v in QWEN3_KANJI_FIXES:
            s = s.replace(k, v)
        tagger = _get_tagger()
        if tagger is not None:
            try:
                import jaconv  # noqa: PLC0415

                words = list(tagger(s))
                parts = []
                for idx_w, w in enumerate(words):
                    parts.append(w.white_space)
                    surf = w.surface
                    kana = getattr(w.feature, "kana", None)
                    next_pos = words[idx_w + 1].feature.pos1 if idx_w + 1 < len(words) else None
                    # Expand 1-kanji verbs with implicit geminate 'っ' (e.g. 達し -> たっし, 発し -> はっし) so 'っ' is never dropped,
                    # and disambiguate 見積 (みつもり) and adnominal 主な (おもな) before a noun without touching 持ち主なのに.
                    if (
                        (w.feature.pos1 == "動詞" and kana and "ッ" in kana and "っ" not in surf and "ッ" not in surf)
                        or surf == "見積"
                        or (surf == "主な" and w.feature.pos1 == "連体詞" and next_pos == "名詞")
                    ):
                        parts.append(jaconv.kata2hira(kana))
                    else:
                        parts.append(surf)
                s = "".join(parts)
            except Exception:
                s = re.sub(r"見積(?!も)", "みつもり", s)
                s = re.sub(r"(?:^|(?<=[、。！？\sはがをにでともへ]))主な(?!の|で|ら)", "おもな", s)
        else:
            s = re.sub(r"見積(?!も)", "みつもり", s)
            s = re.sub(r"(?:^|(?<=[、。！？\sはがをにでともへ]))主な(?!の|で|ら)", "おもな", s)
    for k, v in QWEN3_SYMBOL_FIXES:
        s = s.replace(k, v)
    if s and s[-1] not in "。！？!?.":
        s += "。"
    return s


def qwen3_windows_synth(text, voice, speed, model_id, cache, instruct, temperature, lang):
    """Generate one narration clip with the official PyTorch CustomVoice model."""
    import torch
    from qwen_tts import Qwen3TTSModel

    if "model" not in cache:
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        dtype = torch.float32
        if device != "cpu":
            dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        cache["model"] = Qwen3TTSModel.from_pretrained(
            model_id, device_map=device, dtype=dtype, attn_implementation="sdpa"
        )
    lang = lang or qwen3_lang_code(voice, text)
    kwargs = {} if temperature is None else {"temperature": temperature}
    waves, sr = cache["model"].generate_custom_voice(
        text=_prep_qwen3_text(text, lang), speaker=voice, language=lang.capitalize(),
        instruct=instruct or None, **kwargs
    )
    if not waves or not waves[0].size:
        raise ValueError("Qwen3-TTS produced empty audio")
    samples = waves[0]
    if speed != 1:
        from librosa.effects import time_stretch
        samples = time_stretch(samples, rate=speed)
    return pcm_to_wav(clean_speech(samples.tolist(), sr), sr)


def qwen3_synth(text, voice, speed, model_id, cache, instruct=None, temperature=None, lang=None):
    import numpy as np  # noqa: PLC0415
    from mlx_audio.tts.utils import load_model  # noqa: PLC0415

    if "model" not in cache:
        cache["model"] = load_model(model_id)
    lang = lang or qwen3_lang_code(voice, text)
    results = list(
        cache["model"].generate(
            text=_prep_qwen3_text(text, lang),
            voice=voice,
            instruct=instruct or None,
            temperature=temperature,
            lang_code=lang,
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


QWEN3_DECK_LANGS = {
    "ja": "japanese", "en": "english", "zh": "chinese", "ko": "korean",
    "de": "german", "es": "spanish", "fr": "french", "it": "italian",
    "pt": "portuguese", "ru": "russian",
}


def _norm_alnum(s):
    return "".join(c for c in s if unicodedata.category(c)[0] in ("L", "N"))


def _min_energy_cut(samples, sr, t_left, t_right):
    """Find the lowest-energy sample index after sentence end (t_left) and before next sentence start (t_right)."""
    win = max(1, int(sr * 0.01))
    left = max(0, min(len(samples), round(t_left * sr)))
    right = max(0, min(len(samples), round(t_right * sr)))
    gap = right - left
    # Keep the entire energy window between the two aligned sentences. For
    # adjacent or overlapping alignments, split the ambiguous interval evenly.
    if gap < win:
        return (left + right) // 2
    a = left + min(round(0.28 * sr), gap // 2)
    b = right - min(round(0.10 * sr), gap // 5) - win
    if b < a:
        a, b = left, right - win
    best_i, best_e = a, float("inf")
    step = max(1, win // 2)
    for idx in range(a, b + 1, step):
        chunk = samples[idx : idx + win]
        e = sum(x * x for x in chunk)
        if e < best_e:
            best_e, best_i = e, idx + win // 2
    return best_i


def qwen3_batch_synth(texts, voice, speed, model_id, cache, tmp, instruct=None, temperature=None, all_texts=None, lang=None):
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

    # Keep normal decks in a single continuous take (up to 20 sentences / ~700 chars, ~90s of audio)
    # because longer takes can cause Qwen3-TTS hallucinations or ForcedAligner saturation.
    # Split longer decks evenly so every batch has balanced prosodic context, and bisect on alignment failure.
    max_sents, max_chars = 20, 700
    total_chars = sum(len(t) for t in synth_list)
    n_batches = max(1, math.ceil(len(synth_list) / max_sents), math.ceil(total_chars / max_chars))
    batches = []
    start = 0
    for i in range(n_batches):
        end = round((i + 1) * len(synth_list) / n_batches)
        if end > start:
            batches.append(synth_list[start:end])
            start = end

    wanted = set(texts)
    out = {}
    lang = lang or qwen3_lang_code(voice, " ".join(texts))
    align_lang = lang.capitalize() if lang != "auto" else "Japanese"
    sentinel = {
        "japanese": "いち、に、さん。", "chinese": "一，二，三。", "korean": "하나, 둘, 셋.",
        "german": "Eins, zwei, drei.", "spanish": "Uno, dos, tres.", "french": "Un, deux, trois.",
        "italian": "Uno, due, tre.", "portuguese": "Um, dois, três.", "russian": "Один, два, три.",
    }.get(lang, "One, two, three.")
    queue = list(batches)
    while queue:
        batch = queue.pop(0)
        if cache["aligner"] is None:
            for t in batch:
                if t in wanted:
                    out[t] = qwen3_synth(t, voice, speed, model_id, cache, instruct, temperature, lang=lang)
            continue
        # Join sentences with '\n' (while split_pattern='') and append a dummy sentinel sentence so Qwen3-TTS's final
        # codec EOS token never clips the trailing mora ('〜ます' / '〜ました') of the last sentence in the batch.
        spoken_batch = [_prep_qwen3_text(s, lang) for s in batch]
        synth_spoken = spoken_batch + [sentinel]
        joined = "\n".join(synth_spoken)
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
                    max_tokens=81920,
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
            for spoken_s in synth_spoken:
                target = max(1, len(_norm_alnum(spoken_s)))
                cur_len = 0
                start_i = idx
                while idx < len(items) and cur_len < target:
                    cur_len += len(_norm_alnum(items[idx].text))
                    idx += 1
                if cur_len < target:
                    raise ValueError("incomplete sentence alignment")
                t0, t1 = items[start_i].start_time, items[idx - 1].end_time
                min_dur = max(0.15, target * 0.065) / max(1.0, speed)
                max_dur = max(12.0, target * 0.55) / min(1.0, speed)
                if t1 - t0 < min_dur:
                    raise ValueError("collapsed sentence alignment")
                if t1 - t0 > max_dur:
                    raise ValueError("runaway sentence alignment")
                spans.append((t0, t1))
            max_gap = 4.5 / min(1.0, speed)
            for k in range(len(batch)):
                if spans[k + 1][0] - spans[k][1] > max_gap:
                    raise ValueError("excessive inter-sentence gap")
            samples_list = audio.tolist()
            cuts = [0]
            for k in range(len(batch)):
                cuts.append(_min_energy_cut(samples_list, sr, spans[k][1], spans[k + 1][0]))
            batch_out = {}
            for k, s in enumerate(batch):
                # Window around each sentence's aligned [start - 45ms, end + 450ms] bounded by neighbour cuts
                # so inter-sentence breaths in the \n gap are discarded while trailing devoiced 'す/ます/です' is kept intact.
                i0 = max(cuts[k], int((spans[k][0] - 0.045) * sr))
                i1 = min(cuts[k + 1], int((spans[k][1] + 0.45) * sr))
                if i1 <= i0:
                    i0, i1 = cuts[k], max(cuts[k] + 1, cuts[k + 1])
                seg = clean_speech(samples_list[i0:i1], sr, threshold=0.0015)
                if not seg:
                    raise ValueError("empty segment after alignment")
                batch_out[s] = pcm_to_wav(seg, sr)
            out.update(batch_out)
        except Exception:
            if len(batch) > 1:
                mid = len(batch) // 2
                queue[0:0] = [batch[:mid], batch[mid:]]
            elif batch[0] in wanted:
                out[batch[0]] = qwen3_synth(batch[0], voice, speed, model_id, cache, instruct, temperature, lang=lang)
    return out


def say_voices():
    r = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return []
    seen, out = set(), []
    for line in r.stdout.splitlines():
        m = re.match(r"(.+?)\s+([a-zA-Z]{2,3}[_-][a-zA-Z0-9]+)\s+#", line)
        if m:
            name = m.group(1).strip()
            if name and name not in seen:
                seen.add(name)
                out.append((name, m.group(2)))
    return out


def say_synth(text, voice, speed, tmp):
    out = tmp / "say.aiff"
    cmd = ["say", "-o", str(out), "-r", str(max(1, round(190 * speed)))]
    if voice:
        cmd += ["-v", voice]
    subprocess.run(cmd + ["--", text], check=True, capture_output=True)
    return out.read_bytes(), ".aiff"


def wav_duration(raw):
    """Return WAV duration in seconds, or None if not a readable WAV payload."""
    try:
        with wave.open(io.BytesIO(raw), "rb") as wf:
            rate = wf.getframerate()
            return round(wf.getnframes() / rate, 2) if rate > 0 else None
    except (wave.Error, EOFError, OSError):
        return None


def compress(raw, ext, tmp):
    """Return (bytes, mime). Without a compression tool the audio stays uncompressed."""
    src = tmp / ("in" + ext)
    src.write_bytes(raw)
    if shutil.which("ffmpeg"):
        dst = tmp / "out.mp3"
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-b:a", "96k", str(dst)], capture_output=True)
        if r.returncode == 0 and dst.is_file() and dst.stat().st_size > 0:
            return dst.read_bytes(), "audio/mpeg"
    if shutil.which("afconvert"):
        dst = tmp / "out.m4a"
        r = subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "96000", "-c", "1", str(src), str(dst)], capture_output=True)
        if r.returncode == 0 and dst.is_file() and dst.stat().st_size > 0:
            return dst.read_bytes(), "audio/mp4"
    if ext == ".wav":
        return raw, "audio/wav"
    raise SystemExit("ERROR: the audio could not be converted. Install ffmpeg.")


def trim_clip(uri, seconds):
    """Keep the original PCM frames up to the reviewed end time."""
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("the end time must be a positive number of seconds")
    header, _, encoded = uri.partition(",")
    if header not in ("data:audio/wav;base64", "data:audio/mpeg;base64", "data:audio/mp4;base64"):
        raise ValueError("unsupported embedded audio format")
    raw = base64.b64decode(encoded, validate=True)
    if header != "data:audio/wav;base64":
        if not shutil.which("ffmpeg"):
            raise ValueError("install ffmpeg to trim MP3 or M4A clips")
        with tempfile.TemporaryDirectory() as tmp:
            source = pathlib.Path(tmp) / ("clip.mp3" if "mpeg" in header else "clip.m4a")
            source.write_bytes(raw)
            decoded = pathlib.Path(tmp) / "decoded.wav"
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-c:a", "pcm_s16le", str(decoded)],
                           check=True, capture_output=True)
            if not decoded.is_file() or not decoded.stat().st_size:
                raise ValueError("ffmpeg produced empty audio")
            raw = decoded.read_bytes()
    with wave.open(io.BytesIO(raw), "rb") as audio:
        rate = audio.getframerate()
        nframes = audio.getnframes()
        if rate <= 0 or nframes <= 0:
            raise ValueError("invalid WAV audio header")
        if seconds >= nframes / rate:
            raise ValueError("the end time must be inside the clip")
        frames = round(seconds * rate)
        if not 0 < frames < nframes:
            raise ValueError("the end time must leave at least one frame on each side")
        kept = audio.readframes(frames)
        if len(kept) != frames * audio.getnchannels() * audio.getsampwidth():
            raise ValueError("incomplete audio clip")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as out:
            out.setparams(audio.getparams())
            out.writeframes(kept)
    return "data:audio/wav;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def save_voice_data(deck, original, voice_data):
    src = BLOCK.sub("", original)
    if voice_data is not None:
        if ENGINE not in src:
            raise ValueError("missing engine marker in deck HTML")
        data = json.dumps(voice_data, ensure_ascii=False).replace("</", "<\\/")
        block = '<!-- VOICE:START -->\n<script type="application/json" id="voice-data">%s</script>\n<!-- VOICE:END -->\n' % data
        src = src.replace(ENGINE, block + ENGINE, 1)
    with staged_html(deck, src) as staged, deck_lock(deck):
        try:
            current = deck.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            current = None
        if current != original:
            raise OSError("The deck changed during audio processing. Rerun against the updated deck.")
        staged.replace(deck)


def main():
    setup_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("deck")
    ap.add_argument("--engine", choices=["auto", "voicevox", "kokoro", "qwen3", "say"], default="auto")
    ap.add_argument("--url", help="address of a VOICEVOX or Kokoro-FastAPI engine (127.0.0.1 only)")
    ap.add_argument("--speaker", help="voice: a number for voicevox, a voice name for kokoro, qwen3 or say")
    ap.add_argument("--model", default=("Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice" if platform.system() == "Windows" else QWEN3_DEFAULT_MODEL), help="Hugging Face CustomVoice model ID or local directory for qwen3")
    ap.add_argument("--instruct", default=QWEN3_DEFAULT_INSTRUCT, help="style/emotion instruction for qwen3 (empty string to disable)")
    ap.add_argument("--temperature", type=float, help="sampling temperature for qwen3 (lower is calmer)")
    ap.add_argument("--speed", type=float, default=1.0)
    action = ap.add_mutually_exclusive_group()
    action.add_argument("--list", action="store_true")
    action.add_argument("--remove", action="store_true")
    action.add_argument("--trim-clip", nargs=2, metavar=("SENTENCE", "END_SECONDS"),
                        help="keep the start of an embedded sentence clip up to END_SECONDS")
    a = ap.parse_args()
    if not (math.isfinite(a.speed) and a.speed > 0):
        print("ERROR: --speed must be a finite number greater than zero.")
        return 2
    if a.temperature is not None and not (math.isfinite(a.temperature) and a.temperature >= 0):
        print("ERROR: --temperature must be a finite number greater than or equal to zero.")
        return 2

    if a.url and a.engine in ("qwen3", "say"):
        print("ERROR: --url is only supported with --engine voicevox or --engine kokoro.")
        return 2

    deck = pathlib.Path(a.deck).resolve()
    if not deck.is_file():
        print("ERROR: file not found: %s" % deck)
        return 2
    try:
        with deck_lock(deck):
            src = deck.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print("ERROR: could not read the deck: %s" % e)
        return 2
    if ENGINE not in src:
        print("ERROR: this HTML was not built by this skill.")
        return 2

    old = {}
    m = BLOCK.search(src)
    if m:
        j = re.search(r'<script type="application/json" id="voice-data">(.*?)</script>', m.group(0), re.S)
        if j:
            try:
                parsed = json.loads(j.group(1).replace("<\\/", "</"))
                old = parsed if isinstance(parsed, dict) else {}
            except ValueError:
                old = {}
    if a.remove:
        try:
            if m:
                save_voice_data(deck, src, None)
        except OSError as e:
            print("ERROR: could not remove the embedded audio: %s" % e)
            return 2
        print("Embedded audio removed.")
        return 0

    if a.trim_clip:
        sentence, end = a.trim_clip
        clips = old.get("clips") if isinstance(old, dict) else None
        if not isinstance(clips, dict) or not isinstance(clips.get(sentence), str):
            print("ERROR: no embedded clip matches that exact narration sentence.")
            return 2
        try:
            end_sec = float(end)
            clips[sentence] = trim_clip(clips[sentence], end_sec)
            if isinstance(old.get("durations"), dict):
                old["durations"][sentence] = round(end_sec, 2)
            save_voice_data(deck, src, old)
        except subprocess.CalledProcessError as e:
            detail = (e.stderr.decode("utf-8", errors="replace").strip() if isinstance(e.stderr, bytes) else (e.stderr or "")).strip()
            print("ERROR: could not trim the clip: %s" % (detail or e))
            return 2
        except (ValueError, EOFError, wave.Error, OSError) as e:
            print("ERROR: could not trim the clip: %s" % e)
            return 2
        print("Trimmed the clip to %s seconds: %s" % (end, sentence))
        return 0

    windows_qwen = platform.system() == "Windows"
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
        if platform.system() == "Windows":
            print("  For local Qwen3-TTS on Windows install qwen-tts in this Python environment.")
        if platform.system() == "Darwin":
            print("  For a quick trial, --engine say uses the built-in macOS voice (it sounds robotic).")
        print("The HTML was not changed. Without embedded audio the deck still plays with the device voice.")
        return 2

    if engine == "voicevox":
        try:
            speakers = voicevox_speakers(base)
        except (urllib.error.URLError, HTTPException, OSError, ValueError, KeyError) as e:
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
        except (urllib.error.URLError, HTTPException, OSError, ValueError, KeyError) as e:
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
        head = DeckHead()
        head.feed(src.partition("<!-- SLIDES:START")[0])
        head.close()
        deck_lang = head.attrs.get("lang") or ""
        primary = deck_lang.lower().replace("_", "-").split("-")[0]
        lang = QWEN3_DECK_LANGS.get(primary)
        if deck_lang and not lang:
            print("ERROR: Qwen3 does not support deck language '%s'. Supported language codes: %s."
                  % (deck_lang, ", ".join(sorted(QWEN3_DECK_LANGS))))
            return 2
        version = "v7" if lang in ("japanese", None) else "v4"
        if windows_qwen:
            version += "-torch"
        key = "qwen3:%s:%s:%s:%s:%s:%s" % (version, lang or "infer", a.model, label, a.instruct or "",
                                              "" if a.temperature is None else a.temperature)
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
    try:
        raw_texts = json.loads(html.unescape(rep.group(1)))["texts"]
        if not isinstance(raw_texts, list):
            raise TypeError("texts is not a list")
    except (ValueError, KeyError, TypeError) as e:
        print("The narration could not be read (%s). Make the deck pass check.py first." % e)
        return 2
    texts = list(dict.fromkeys(t for t in raw_texts if isinstance(t, str) and t.strip()))

    reuse = old["clips"] if (old.get("voice"), old.get("speed")) == (key, a.speed) and isinstance(old.get("clips"), dict) else {}
    reuse_durs = old["durations"] if (old.get("voice"), old.get("speed")) == (key, a.speed) and isinstance(old.get("durations"), dict) else {}
    clips = {t: reuse[t] for t in texts if t in reuse}
    durations = {t: reuse_durs[t] for t in texts if t in reuse_durs}
    todo = [t for t in texts if t not in clips]
    print("%d sentences, %d to generate, voice: %s (generated on this computer)" % (len(texts), len(todo), label))
    kokoro_pipelines = {}
    qwen3_cache = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        try:
            qwen3_pre = (
                qwen3_batch_synth(todo, label, a.speed, a.model, qwen3_cache, tmp, a.instruct, a.temperature, all_texts=texts, lang=lang)
                if engine == "qwen3" and not windows_qwen and todo
                else {}
            )
        except (ImportError, urllib.error.URLError, HTTPException, OSError, subprocess.CalledProcessError, ValueError, RuntimeError) as e:
            print("Audio could not be generated (%s)" % e)
            print("The HTML was not changed.")
            return 1
        for n, t in enumerate(todo, 1):
            try:
                if engine == "voicevox":
                    raw, ext = voicevox_synth(base, t, sid, a.speed), ".wav"
                elif engine == "kokoro-api":
                    raw, ext = kokoro_api_synth(kokoro_base, t, label, a.speed), ".wav"
                elif engine == "kokoro-py":
                    raw, ext = kokoro_py_synth(t, label, a.speed, kokoro_pipelines), ".wav"
                elif engine == "qwen3" and windows_qwen:
                    raw = qwen3_windows_synth(t, label, a.speed, a.model, qwen3_cache, a.instruct, a.temperature, lang)
                    ext = ".wav"
                elif engine == "qwen3":
                    raw, ext = qwen3_pre[t], ".wav"
                else:
                    raw, ext = say_synth(t, label, a.speed, tmp)
                if ext == ".wav":
                    dur = wav_duration(raw)
                    if dur is not None:
                        durations[t] = dur
                data, mime = compress(raw, ext, tmp)
            except (ImportError, urllib.error.URLError, HTTPException, OSError, subprocess.CalledProcessError, ValueError, RuntimeError, KeyError) as e:
                print("Audio could not be generated: %s (%s)" % (t[:30], e))
                print("The HTML was not changed.")
                return 1
            clips[t] = "data:%s;base64,%s" % (mime, base64.b64encode(data).decode("ascii"))
            if n % 10 == 0:
                print("  %d / %d" % (n, len(todo)))

    try:
        payload = {"voice": key, "label": label, "speed": a.speed, "clips": {t: clips[t] for t in texts}}
        if durations:
            payload["durations"] = {t: durations[t] for t in texts if t in durations}
        save_voice_data(deck, src, payload)
    except OSError as e:
        print("ERROR: could not save the embedded audio: %s" % e)
        return 2
    print("Audio embedded: %s (%.1f MB)" % (deck.name, deck.stat().st_size / 1e6))
    if engine == "voicevox":
        print("NOTE: VOICEVOX / AivisSpeech voices usually require a credit when the deck is published (for example \"VOICEVOX:%s\"). Check the terms of use of the voice you chose." % label.split("（")[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
