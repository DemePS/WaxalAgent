#!/usr/bin/env python3
"""Soynade API evaluation on the ALFFA Wolof test set.

Runs two batches against api.soynade.ai and writes every audio file to disk so a
human can listen to them:

  STT  20 real ALFFA clips  -> /v1/audio/transcriptions  -> compared with the
       corpus reference transcript (word error rate), then the recognised Wolof
       is translated to French with /v1/translations.

  TTS  the same 20 reference sentences -> /v1/text-to-speech (language=wo).
       Round-tripped back through /v1/audio/transcriptions so each generated
       clip gets an intelligibility score against the text it was built from.

Output tree (git-ignored):

    eval/soynade/
        stt/<utt-id>.wav        source clip downloaded from ALFFA
        tts/<utt-id>.wav        Wolof speech generated from the reference text
        results.json            every field, machine readable
        report.md               side-by-side table for reading

Usage:  uv run python scripts/soynade_eval.py [-n 20]

Reads SOYNADE_API_KEY from the environment or from .env at the repo root.
The key is never printed.
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import pathlib
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import uuid

API = "https://api.soynade.ai"
ALFFA = ("https://raw.githubusercontent.com/getalp/ALFFA_PUBLIC/master/"
         "ASR/WOLOF/data/test")
UA = {"User-Agent": "waxal-eval"}

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO / "eval" / "soynade"


# --------------------------------------------------------------------------- #
# credentials
# --------------------------------------------------------------------------- #
def load_key() -> tuple[str, str]:
    """Return (key, where it came from). .env wins over the environment.

    .env is the one place the key is kept, so a stale `export SOYNADE_API_KEY`
    left over in a shell must not shadow it. The key itself is never printed.
    """
    import os

    env = REPO / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if "SOYNADE" in k.upper():
                key = v.strip().strip('"').strip("'").strip()
                if key:
                    return key, f".env ({k.strip()})"

    for name in ("SOYNADE_API_KEY", "SOYNADE_KEY"):
        raw = os.environ.get(name)
        if raw and raw.strip():
            return raw.strip().strip('"').strip("'").strip(), f"environment ({name})"

    sys.exit("No SOYNADE_API_KEY in .env at the repo root or in the environment")


# --------------------------------------------------------------------------- #
# http
# --------------------------------------------------------------------------- #
RETRY_ON = {429, 500, 502, 503, 504}
MAX_TRIES = 7
PACE = 3.0  # seconds between API calls, to stay under the rate limit


def http(req: urllib.request.Request, timeout: int = 180,
         tries: int = MAX_TRIES) -> tuple[int, bytes]:
    """POST/GET with backoff on rate limits and transient server errors.

    A 429 is a refusal: the request is not billed, so retrying costs nothing
    but time. The server's Retry-After is honoured when it sends one,
    otherwise the wait doubles: 5, 10, 20, 40, 60, 60 seconds. The long tail
    matters because the limit looks like a per-minute window, not a burst.
    """
    delay = 5.0
    max_delay = 60.0
    for attempt in range(1, tries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            body = e.read()
            if e.code not in RETRY_ON or attempt == tries:
                return e.code, body
            wait = delay
            retry_after = e.headers.get("Retry-After") if e.headers else None
            if retry_after:
                try:
                    wait = max(wait, float(retry_after))
                except ValueError:
                    pass
            print(f"      {e.code}, waiting {wait:.0f}s "
                  f"(attempt {attempt}/{tries - 1})")
            time.sleep(wait)
            delay = min(delay * 2, max_delay)
        except Exception as e:  # network hiccup
            if attempt == tries:
                return 0, repr(e).encode()
            time.sleep(delay)
            delay = min(delay * 2, max_delay)
    return 0, b"exhausted retries"


def fetch(url: str, timeout: int = 120) -> bytes:
    status, body = http(urllib.request.Request(url, headers=UA), timeout)
    if status != 200:
        raise RuntimeError(f"GET {url} -> {status}")
    return body


def post_json(key: str, path: str, payload: dict) -> tuple[int, bytes]:
    time.sleep(PACE)
    req = urllib.request.Request(
        API + path,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}", **UA},
    )
    return http(req)


def post_audio(key: str, path: str, fields: dict, name: str,
               blob: bytes) -> tuple[int, bytes]:
    time.sleep(PACE)
    boundary = "----waxal" + uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += (f"--{boundary}\r\n"
                 f'Content-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                 ).encode()
    body += (f"--{boundary}\r\n"
             f'Content-Disposition: form-data; name="file"; filename="{name}"\r\n'
             f"Content-Type: audio/wav\r\n\r\n").encode() + blob + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        API + path, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Authorization": f"Bearer {key}", **UA},
    )
    return http(req)


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def normalise(text: str) -> list[str]:
    """Lowercase, drop punctuation, keep Wolof diacritics (à ë ñ ŋ ó)."""
    text = unicodedata.normalize("NFC", text.lower())
    text = re.sub(r"[^\w\sàáâäãåèéêëìíîïòóôöõùúûüñŋçÀ-ÿ'-]", " ", text)
    text = text.replace("'", " ").replace("-", " ")
    return text.split()


def wer(ref: list[str], hyp: list[str]) -> tuple[float, int, int, int]:
    """Levenshtein on words -> (rate, substitutions, deletions, insertions)."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    bt = [[""] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0], bt[i][0] = i, "d"
    for j in range(1, m + 1):
        d[0][j], bt[0][j] = j, "i"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                d[i][j], bt[i][j] = d[i - 1][j - 1], "="
                continue
            sub, dele, ins = d[i - 1][j - 1] + 1, d[i - 1][j] + 1, d[i][j - 1] + 1
            best = min(sub, dele, ins)
            d[i][j] = best
            bt[i][j] = "s" if best == sub else ("d" if best == dele else "i")
    i, j = n, m
    counts = collections.Counter()
    while i > 0 or j > 0:
        op = bt[i][j]
        counts[op] += 1
        if op in ("=", "s"):
            i, j = i - 1, j - 1
        elif op == "d":
            i -= 1
        else:
            j -= 1
    return (d[n][m] / max(1, n), counts["s"], counts["d"], counts["i"])


def duration(blob: bytes) -> float:
    try:
        import soundfile as sf

        info = sf.info(io.BytesIO(blob))
        return info.frames / info.samplerate
    except Exception:
        return 0.0


# --------------------------------------------------------------------------- #
# sample selection
# --------------------------------------------------------------------------- #
def select(count: int) -> list[tuple[str, str]]:
    """Deterministic spread over both ALFFA test speakers, mid-length sentences."""
    text = fetch(f"{ALFFA}/text").decode("utf-8")
    by_speaker: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        uid, _, transcript = line.partition(" ")
        transcript = transcript.strip()
        if not transcript:
            continue
        parts = uid.split("_")
        if len(parts) < 2:
            continue
        by_speaker[parts[1]].append((uid, transcript))

    per = max(1, count // max(1, len(by_speaker)))
    picked: list[tuple[str, str]] = []
    for speaker in sorted(by_speaker):
        pool = [r for r in by_speaker[speaker] if 5 <= len(r[1].split()) <= 14]
        pool = pool or by_speaker[speaker]
        step = max(1, len(pool) // per)
        picked += pool[::step][:per]
    return picked[:count]


def clip_url(uid: str) -> str:
    return f"{ALFFA}/wav/{uid.split('_')[1]}/{uid}.wav"


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    global PACE  # must precede every use of the name in this function

    ap = argparse.ArgumentParser()
    ap.add_argument("-n", type=int, default=20, help="how many utterances")
    ap.add_argument("--target", default="fr", help="translation target language")
    ap.add_argument("--pace", type=float, default=PACE,
                    help="seconds between API calls (raise it if you see 429s)")
    args = ap.parse_args()

    PACE = args.pace

    key, origin = load_key()
    print(f"key loaded from {origin}: {key[:5]}…{key[-2:]} ({len(key)} chars)")

    # "reply" holds the spoken answers: audio synthesised from Wolof that was
    # itself translated back from French. The older tts/ clips were read from
    # the corpus sentence directly and are not comparable.
    stt_dir, tts_dir = OUT / "stt", OUT / "reply"
    for d in (stt_dir, tts_dir):
        d.mkdir(parents=True, exist_ok=True)

    samples = select(args.n)
    print(f"selected {len(samples)} utterances from the ALFFA test set\n")

    # Anything an earlier run already paid for is reused: a 429 only stopped
    # some utterances, and recognising the others again would bill them twice.
    done: dict[str, dict] = {}
    previous = OUT / "results.json"
    if previous.exists():
        try:
            for r in json.loads(previous.read_text())["rows"]:
                if r.get("asr"):
                    done[r["id"]] = r
        except (ValueError, KeyError):
            pass
    if done:
        print(f"reusing {len(done)} transcription(s) from the previous run\n")

    results, audio_seconds, tts_chars = [], 0.0, 0

    for idx, (uid, reference) in enumerate(samples, 1):
        row: dict = {"id": uid, "reference": reference}
        print(f"[{idx:2d}/{len(samples)}] {uid}")

        cached_row = done.get(uid)

        # ---- STT on the real recording -------------------------------------
        src = stt_dir / f"{uid}.wav"
        if src.exists():
            blob = src.read_bytes()
        else:
            blob = fetch(clip_url(uid))
            src.write_bytes(blob)
        secs = duration(blob)
        row["source_wav"] = str(src.relative_to(REPO))
        row["source_seconds"] = round(secs, 2)

        if cached_row and cached_row.get("asr"):
            status, body = 200, None
            row["asr"] = cached_row["asr"]
            for field in ("wer", "sub", "dele", "ins"):
                if field in cached_row:
                    row[field] = cached_row[field]
            print(f"      asr  {row['asr']}  (reused, not re-billed)")
        else:
            status, body = post_audio(key, "/v1/audio/transcriptions",
                                      {"source_language": "wo"},
                                      f"{uid}.wav", blob)
            if status == 200:
                audio_seconds += secs  # only an accepted call is billed
                row["asr"] = json.loads(body).get("text", "")
                rate, s, d, i = wer(normalise(reference), normalise(row["asr"]))
                row.update(wer=round(rate, 4), sub=s, dele=d, ins=i)
                print(f"      ref  {reference}")
                print(f"      asr  {row['asr']}")
                print(f"      WER  {rate:.1%}")
        if status != 200:
            row["asr_error"] = f"{status}: {body[:200].decode('utf-8', 'replace')}"
            print("      ASR FAILED", row["asr_error"])
            if status in (401, 403):
                sys.exit(
                    f"\nThe API rejected the key loaded from {origin} ({status}).\n"
                    "Nothing was billed and no report was written. Check the key in\n"
                    ".env against the one shown in console.soynade.ai, then rerun."
                )

        # ---- translate the recognised Wolof --------------------------------
        if cached_row and cached_row.get(args.target):
            row[args.target] = cached_row[args.target]
            print(f"      {args.target}   {row[args.target]}  (reused)")
        elif row.get("asr"):
            status, body = post_json(key, "/v1/translations", {
                "text": row["asr"], "source_language": "wo",
                "target_language": args.target})
            if status == 200:
                row[args.target] = json.loads(body).get("translated_text", "")
                print(f"      {args.target}   {row[args.target]}")
            else:
                row["mt_error"] = f"{status}: {body[:200].decode('utf-8', 'replace')}"

        # ---- the reply path: French text -> Wolof text -> Wolof speech -----
        # This is the direction the product needs. The agent thinks in French,
        # so an answer starts as French text, has to be put into Wolof, and
        # then spoken. Synthesising the corpus sentence directly would skip the
        # translation and measure something we never do.
        if cached_row and cached_row.get("reply_wo"):
            row["reply_wo"] = cached_row["reply_wo"]
            row["reply_wer"] = cached_row.get("reply_wer")
            print(f"      wo'  {row['reply_wo']}  (reused)")
        elif row.get(args.target):
            status, body = post_json(key, "/v1/translations", {
                "text": row[args.target], "source_language": args.target,
                "target_language": "wo"})
            if status == 200:
                row["reply_wo"] = json.loads(body).get("translated_text", "")
                # How much of the original Wolof survives the round trip
                # wo -> fr -> wo. Not a translation score on its own: the ASR
                # errors from the first leg are baked in.
                rate, *_ = wer(normalise(reference), normalise(row["reply_wo"]))
                row["reply_wer"] = round(rate, 4)
                print(f"      wo'  {row['reply_wo']}")
                print(f"      round trip WER {rate:.1%}")
            else:
                row["reply_mt_error"] = \
                    f"{status}: {body[:200].decode('utf-8', 'replace')}"
                print("      BACK-TRANSLATION FAILED", row["reply_mt_error"])

        spoken = row.get("reply_wo")
        if spoken:
            gen = tts_dir / f"{uid}.wav"
            cached = gen.exists()
            if cached:
                tts_blob = gen.read_bytes()
                status = 200
            else:
                status, tts_blob = post_json(key, "/v1/text-to-speech",
                                             {"text": spoken, "language": "wo"})
                if status == 200:
                    gen.write_bytes(tts_blob)
            if status == 200:
                if not cached:  # a cached clip was billed on an earlier run
                    tts_chars += len(spoken)
                row["tts_wav"] = str(gen.relative_to(REPO))
                row["tts_seconds"] = round(duration(tts_blob), 2)

                # Is the spoken answer intelligible? Read it back and compare
                # with the Wolof we asked it to say -- not with the corpus
                # sentence, which it was never given.
                # Only a row from this pipeline can be reused: an older one
                # read back a clip synthesised from the corpus sentence.
                if (cached_row and cached_row.get("reply_wo")
                        and cached_row.get("tts_asr")):
                    row["tts_asr"] = cached_row["tts_asr"]
                    row["tts_wer"] = cached_row.get("tts_wer")
                    print(f"      tts  {row['tts_seconds']:.2f}s  (reused)")
                else:
                    st2, body2 = post_audio(key, "/v1/audio/transcriptions",
                                            {"source_language": "wo"},
                                            f"{uid}_tts.wav", tts_blob)
                    if st2 == 200:
                        row["tts_asr"] = json.loads(body2).get("text", "")
                        rate, *_ = wer(normalise(spoken), normalise(row["tts_asr"]))
                        row["tts_wer"] = round(rate, 4)
                        audio_seconds += row["tts_seconds"]
                        print(f"      tts  {row['tts_seconds']:.2f}s  "
                              f"read-back WER {rate:.1%}")
            else:
                row["tts_error"] = \
                    f"{status}: {tts_blob[:200].decode('utf-8', 'replace')}"
                print("      TTS FAILED", row["tts_error"])

        results.append(row)
        time.sleep(0.4)

    # ---- aggregate ---------------------------------------------------------
    def corpus_wer(ref_key: str, hyp_key: str) -> float | None:
        errs = total = 0
        for r in results:
            if not r.get(hyp_key):
                continue
            ref = normalise(r[ref_key])
            rate, *_ = wer(ref, normalise(r[hyp_key]))
            errs += rate * len(ref)
            total += len(ref)
        return errs / total if total else None

    summary = {
        "n": len(results),
        "stt_ok": sum(1 for r in results if r.get("asr")),
        "mt_ok": sum(1 for r in results if r.get(args.target)),
        "back_ok": sum(1 for r in results if r.get("reply_wo")),
        "tts_ok": sum(1 for r in results if r.get("tts_wav")),
        # Recognition: what the model heard vs what the corpus says.
        "corpus_wer_real_audio": corpus_wer("reference", "asr"),
        # Full round trip wo -> fr -> wo, measured on text.
        "corpus_wer_round_trip": corpus_wer("reference", "reply_wo"),
        # Intelligibility of the spoken answer: read back vs what we asked it
        # to say, so it does not inherit the round-trip losses.
        "corpus_wer_tts_roundtrip": corpus_wer("reply_wo", "tts_asr"),
        "audio_minutes_billed": round(audio_seconds / 60, 3),
        "tts_characters": tts_chars,
        "estimated_usd": round(audio_seconds / 60 * 0.30 + tts_chars / 1000 * 0.22, 3),
    }

    (OUT / "results.json").write_text(
        json.dumps({"summary": summary, "rows": results},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# Soynade evaluation — ALFFA Wolof test set", ""]
    cw = summary["corpus_wer_real_audio"]
    tr = summary["corpus_wer_round_trip"]
    rt = summary["corpus_wer_tts_roundtrip"]
    lines += [
        f"- utterances: **{summary['n']}**",
        f"- inbound, WER on real audio (wo speech -> wo text): **{cw:.1%}**"
        if cw is not None else "- corpus WER: n/a",
        f"- round trip, WER on text (wo -> {args.target} -> wo): **{tr:.1%}**"
        if tr is not None else "",
        f"- outbound, read-back WER of the spoken answer: **{rt:.1%}**"
        if rt is not None else "",
        f"- billed: ~{summary['audio_minutes_billed']} audio min + "
        f"{summary['tts_characters']} chars ≈ **${summary['estimated_usd']}**",
        "",
        "Listen: `eval/soynade/stt/<id>.wav` is the human recording, "
        "`eval/soynade/reply/<id>.wav` is the spoken answer "
        f"(Wolof translated back from {args.target}, then synthesised).",
        "",
    ]
    for r in results:
        lines += [f"## {r['id']}", ""]
        lines += [f"- **reference** &nbsp; `{r['reference']}`"]
        if r.get("asr"):
            lines += [f"- **recognised** &nbsp; `{r['asr']}` — WER {r['wer']:.1%}"]
        if r.get(args.target):
            lines += [f"- **{args.target}** &nbsp; {r[args.target]}"]
        if r.get("reply_wo"):
            lines += [f"- **back to wolof** &nbsp; `{r['reply_wo']}` — "
                      f"round-trip WER {r['reply_wer']:.1%}"]
        if r.get("tts_asr"):
            lines += [f"- **spoken answer read back** &nbsp; `{r['tts_asr']}` — "
                      f"WER {r['tts_wer']:.1%}"]
        src_s, tts_s = r.get("source_seconds"), r.get("tts_seconds")
        lines += [f"- audio: human {src_s}s / spoken answer {tts_s}s", ""]
    (OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n" + "=" * 70)
    for k, v in summary.items():
        print(f"  {k:28s} {v if not isinstance(v, float) else round(v, 4)}")
    print(f"\nwrote {OUT.relative_to(REPO)}/report.md and results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
