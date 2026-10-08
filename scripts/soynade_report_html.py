#!/usr/bin/env python3
"""Build a readable HTML page from the Soynade evaluation results.

Reads eval/soynade/results.json and writes an HTML report in French, split in
two independent parts so the two models are never read as one thing:

  1. Synthèse vocale (oolel-voices)  — text sent, expected reading, response.
  2. Reconnaissance vocale (oolel-speech-v1) — audio sent, expected transcript,
     response, then the separate translation call.

The page is a single self-contained file: inline CSS and JS, no CDN, no build
step. Without --embed it reads the WAVs by relative path, so it must stay in
eval/soynade/. With --embed every clip is carried inside the page, each one
stored once even though the human recordings appear in both parts.

Usage:  uv run python scripts/soynade_report_html.py [--embed]
        (run it after scripts/soynade_eval.py; it only reads results.json
         and costs nothing)
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import pathlib
import re
import sys
import unicodedata

REPO = pathlib.Path(__file__).resolve().parent.parent
OUT = REPO / "eval" / "soynade"

# With --embed every clip is carried inside the page as a data: URI, so the
# single file can be sent to someone who has none of the audio.
EMBED = False

# Clips collected while building, keyed so each one is embedded only once.
CLIPS: dict[str, str] = {}

# Keys that are bookkeeping rather than a translation target.
RESERVED = {
    "id", "reference", "source_wav", "source_seconds", "asr", "wer",
    "sub", "dele", "ins", "asr_error", "mt_error", "tts_error",
    "tts_wav", "tts_seconds", "tts_asr", "tts_wer",
    "reply_wo", "reply_wer", "reply_mt_error",
}


def normalise(text: str) -> list[str]:
    """Same comparison rules as the evaluation: case and punctuation ignored."""
    text = unicodedata.normalize("NFC", text.lower())
    text = re.sub(r"[^\w\sàáâäãåèéêëìíîïòóôöõùúûüñŋçÀ-ÿ'-]", " ", text)
    text = text.replace("'", " ").replace("-", " ")
    return text.split()


def align(ref: list[str], hyp: list[str]) -> list[tuple[str, str, str]]:
    """Word-level Levenshtein backtrace -> [(op, ref_word, hyp_word)]."""
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

    ops: list[tuple[str, str, str]] = []
    i, j = n, m
    while i > 0 or j > 0:
        op = bt[i][j]
        if op in ("=", "s"):
            ops.append((op, ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif op == "d":
            ops.append((op, ref[i - 1], ""))
            i -= 1
        else:
            ops.append((op, "", hyp[j - 1]))
            j -= 1
    return list(reversed(ops))


def marked(ops: list[tuple[str, str, str]], side: str) -> str:
    """Render one side of the alignment with the mismatches highlighted."""
    css = {"s": "sub", "d": "del", "i": "ins"}
    out = []
    for op, ref_w, hyp_w in ops:
        word = ref_w if side == "ref" else hyp_w
        if op == "d" and side == "hyp":
            out.append('<span class="gap" title="mot omis">·</span>')
            continue
        if op == "i" and side == "ref":
            out.append('<span class="gap" title="mot inventé">·</span>')
            continue
        if not word:
            continue
        esc = html.escape(word)
        if op == "=":
            out.append(f"<span>{esc}</span>")
        else:
            title = {"s": "substitué", "d": "omis", "i": "inventé"}[op]
            out.append(f'<span class="{css[op]}" title="{title}">{esc}</span>')
    return " ".join(out)


def pct(value) -> str:
    return "—" if value is None else f"{value * 100:.1f} %"


def badge(value, label: str = "WER") -> str:
    """Colour a WER by how usable it is."""
    if value is None:
        return '<span class="badge none">aucun résultat</span>'
    klass = "good" if value <= 0.15 else ("ok" if value <= 0.35 else "bad")
    return f'<span class="badge {klass}">{label} {pct(value)}</span>'


def clip(path: pathlib.Path, key: str, seconds=None, note: str = "") -> str:
    """An <audio> element, or a note when the clip was never produced.

    In embed mode the audio is registered once in CLIPS and the element only
    carries its key; a line of JS hands out the sources on load. The human
    recordings appear in both parts of the page, and this keeps the file from
    carrying them twice.
    """
    if not path.exists():
        return '<p class="missing"><em>non généré</em></p>'
    if EMBED:
        if key not in CLIPS:
            CLIPS[key] = base64.b64encode(path.read_bytes()).decode("ascii")
        tag = f'<audio controls preload="none" data-clip="{key}"></audio>'
    else:
        src = html.escape(path.relative_to(OUT).as_posix())
        tag = f'<audio controls preload="none" src="{src}"></audio>'
    meta = []
    if isinstance(seconds, (int, float)):
        meta.append(f"{seconds:.2f} s")
    if note:
        meta.append(note)
    extra = f'<small>{" · ".join(meta)}</small>' if meta else ""
    return f'<div class="audio">{tag}{extra}</div>'


def step(label: str, body: str) -> str:
    return (f'<div class="step"><span class="who">{label}</span>'
            f'<div class="val">{body}</div></div>')


def reply_card(row: dict, target: str) -> str:
    """The answer path: French text -> Wolof text -> Wolof speech."""
    uid = html.escape(row["id"])
    reference = row.get("reference", "")
    wer_value = row.get("reply_wer")

    parts = [f'<article class="card" data-wer="{wer_value if wer_value is not None else ""}">',
             f'<h3>{uid} {badge(wer_value, "aller-retour")}</h3>']

    parts.append(step(
        f"texte {target} envoyé",
        f'<p class="words plain">{html.escape(row.get(target, "—"))}</p>'
        '<p class="hint">ce que l’agent aurait rédigé ; ici, la traduction '
        'obtenue en partie 2</p>'))

    if row.get("reply_wo"):
        ops = align(normalise(reference), normalise(row["reply_wo"]))
        parts.append(step(
            "texte wolof obtenu",
            f'<p class="words">{marked(ops, "hyp")}</p>'
            f'<p class="hint">appel <code>/v1/translations</code> '
            f'{target}&nbsp;→&nbsp;wo</p>'))
        parts.append(step(
            "attendu",
            f'<p class="words">{marked(ops, "ref")}</p>'
            '<p class="hint">la phrase wolof de départ : l’écart cumule la '
            'reconnaissance et les deux traductions</p>'))
    elif row.get("reply_mt_error"):
        parts.append(step("texte wolof obtenu",
                          '<p class="err">échec de la traduction — '
                          f'{html.escape(row["reply_mt_error"][:120])}</p>'))

    body = clip(OUT / "reply" / f'{row["id"]}.wav', f'{row["id"]}:t',
                row.get("tts_seconds"),
                "voix oolel-voices, lisant le wolof ci-dessus")
    if row.get("tts_error"):
        body += ('<p class="err">échec de la synthèse — '
                 f'{html.escape(row["tts_error"][:120])}</p>')
    parts.append(step("réponse parlée", body))

    if row.get("tts_asr"):
        ops = align(normalise(row.get("reply_wo", "")),
                    normalise(row["tts_asr"]))
        parts.append(step(
            "intelligibilité",
            f'<p class="words">{marked(ops, "hyp")} '
            f'{badge(row.get("tts_wer"), "relecture")}</p>'
            '<p class="hint">ce que la reconnaissance comprend en réécoutant le '
            'clip, comparé au texte wolof qu’on lui a demandé de dire</p>'))

    parts.append(step(
        "pour l’oreille",
        clip(OUT / "stt" / f'{row["id"]}.wav', f'{row["id"]}:h',
             row.get("source_seconds"),
             "un humain lisant la phrase de départ (corpus ALFFA)")))

    parts.append("</article>")
    return "\n".join(parts)


def stt_card(row: dict, target: str) -> str:
    """Recognition: the audio we sent, the human transcript, what came back."""
    uid = html.escape(row["id"])
    reference = row.get("reference", "")
    wer_value = row.get("wer")

    parts = [f'<article class="card" data-wer="{wer_value if wer_value is not None else ""}">',
             f'<h3>{uid} {badge(wer_value)}</h3>']

    parts.append(step("audio envoyé",
                      clip(OUT / "stt" / f'{row["id"]}.wav', f'{row["id"]}:h',
                           row.get("source_seconds"), "voix humaine")))

    if row.get("asr"):
        ops = align(normalise(reference), normalise(row["asr"]))
        parts.append(step("résultat attendu",
                          f'<p class="words">{marked(ops, "ref")}</p>'))
        body = f'<p class="words">{marked(ops, "hyp")}</p>'
        if any(k in row for k in ("sub", "dele", "ins")):
            body += (f'<p class="hint">{row.get("sub", 0)} substitué(s) · '
                     f'{row.get("dele", 0)} omis · '
                     f'{row.get("ins", 0)} inventé(s)</p>')
        parts.append(step("réponse du modèle", body))
    else:
        parts.append(step("résultat attendu",
                          f'<p class="words plain">{html.escape(reference)}</p>'))
        parts.append(step("réponse du modèle",
                          '<p class="err">échec de la reconnaissance — '
                          f'{html.escape(row.get("asr_error", "")[:120])}</p>'))

    if row.get(target):
        parts.append(step(
            f"traduction ({target})",
            f'<p class="words plain">{html.escape(row[target])}</p>'
            '<p class="hint">appel distinct : la sortie ci-dessus est renvoyée '
            'à <code>/v1/translations</code></p>'))
    elif row.get("mt_error"):
        parts.append(step(f"traduction ({target})",
                          '<p class="err">échec de la traduction — '
                          f'{html.escape(row["mt_error"][:120])}</p>'))

    parts.append("</article>")
    return "\n".join(parts)


STYLE = """
:root {
  --bg: #fbfaf7; --ink: #1d1c1a; --muted: #6a6560; --line: #e2ded6;
  --card: #ffffff; --good: #1f7a4d; --ok: #9a6b11; --bad: #a32f28;
  --sub: #fde2e0; --del: #e7ecfb; --ins: #fdf0d8;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2.5rem 1.25rem 4rem; background: var(--bg); color: var(--ink);
  font: 16px/1.55 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
}
main { max-width: 54rem; margin: 0 auto; }
h1 { font-size: 1.6rem; margin: 0 0 .35rem; letter-spacing: -.01em; }
.lede { color: var(--muted); margin: 0 0 1.5rem; max-width: 44rem; }
.summary { display: flex; flex-wrap: wrap; gap: .75rem; margin-bottom: 1.25rem; }
.stat {
  background: var(--card); border: 1px solid var(--line); border-radius: .6rem;
  padding: .7rem 1rem; min-width: 8.5rem;
}
.stat b { display: block; font-size: 1.4rem; font-weight: 650; }
.stat span { color: var(--muted); font-size: .8rem; }
.about {
  background: var(--card); border: 1px solid var(--line); border-radius: .7rem;
  padding: .9rem 1.25rem 1rem; margin-bottom: 2.5rem;
}
.about h2, .legend-title {
  font-size: .72rem; font-weight: 600; letter-spacing: .05em; text-transform: uppercase;
  color: var(--muted); margin: 0 0 .6rem;
}
.about dl { margin: 0; display: grid; grid-template-columns: 11rem 1fr; gap: .35rem .9rem; }
.about dt { font-size: .85rem; color: var(--muted); }
.about dd { margin: 0; font-size: .9rem; }
code { background: #f3f0ea; padding: .05rem .3rem; border-radius: .25rem; font-size: .85em; }
a { color: inherit; text-decoration-color: #bdb6ab; text-underline-offset: 2px; }
.part { margin-bottom: 3rem; }
.part > header { border-top: 2px solid var(--ink); padding-top: .8rem; margin-bottom: 1rem; }
.part h2 { font-size: 1.25rem; margin: 0 0 .3rem; letter-spacing: -.01em; }
.part .what { color: var(--muted); margin: 0 0 .9rem; font-size: .92rem; max-width: 44rem; }
.part .flow {
  display: flex; flex-wrap: wrap; gap: .4rem; align-items: center;
  font-size: .78rem; color: var(--muted); margin-bottom: 1rem;
}
.flow b { font-weight: 600; color: var(--ink); background: #f3f0ea;
  padding: .15rem .5rem; border-radius: 1rem; }
.legend, .controls {
  display: flex; flex-wrap: wrap; align-items: center; gap: .9rem;
  font-size: .85rem; color: var(--muted); margin-bottom: 1rem;
}
.key { padding: .1rem .4rem; border-radius: .25rem; color: var(--ink); }
.key.sub { background: var(--sub); } .key.del { background: var(--del); }
.key.ins { background: var(--ins); }
button {
  font: inherit; font-size: .85rem; padding: .3rem .7rem; cursor: pointer;
  background: var(--card); border: 1px solid var(--line); border-radius: .4rem;
}
button[aria-pressed="true"] { background: var(--ink); color: var(--bg); border-color: var(--ink); }
.card {
  background: var(--card); border: 1px solid var(--line); border-radius: .7rem;
  padding: 1.1rem 1.25rem; margin-bottom: .9rem;
}
.card h3 {
  font-size: .82rem; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
  color: var(--muted); margin: 0 0 .9rem; display: flex; align-items: center; gap: .6rem;
}
.badge { font-size: .75rem; padding: .12rem .5rem; border-radius: 1rem; letter-spacing: 0; text-transform: none; }
.badge.good { background: #e3f3ea; color: var(--good); }
.badge.ok { background: #fbf0d8; color: var(--ok); }
.badge.bad { background: #fae5e3; color: var(--bad); }
.badge.none { background: #eee; color: var(--muted); }
.step { display: flex; gap: .9rem; align-items: baseline; margin-bottom: .7rem; }
.step:last-child { margin-bottom: 0; }
.who {
  flex: 0 0 8.5rem; font-size: .72rem; text-transform: uppercase; letter-spacing: .05em;
  color: var(--muted); text-align: right;
}
.val { flex: 1 1 auto; min-width: 0; }
.words { margin: 0; font-size: 1.05rem; }
.words span { padding: .05rem .15rem; border-radius: .2rem; }
.words .sub { background: var(--sub); } .words .del { background: var(--del); }
.words .ins { background: var(--ins); }
.words .gap { color: #c3bdb4; }
.hint { margin: .3rem 0 0; font-size: .78rem; color: var(--muted); }
.err { margin: .2rem 0 0; font-size: .82rem; color: var(--bad); }
.missing { margin: 0; } .missing em { font-size: .85rem; color: #b9b2a8; }
.audio { display: flex; flex-wrap: wrap; align-items: center; gap: .6rem; }
.audio audio { width: 20rem; max-width: 100%; height: 2.3rem; }
.audio small { font-size: .78rem; color: var(--muted); }
footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--line);
  font-size: .8rem; color: var(--muted); }
@media (max-width: 36rem) {
  .step { display: block; } .who { text-align: left; display: block; margin-bottom: .2rem; }
  .about dl { grid-template-columns: 1fr; gap: .1rem; }
}
"""

SCRIPT = """
// Hand out the embedded clips, each stored once however often it is shown.
if (window.CLIPS) {
  document.querySelectorAll('audio[data-clip]').forEach(function (a) {
    a.src = 'data:audio/wav;base64,' + window.CLIPS[a.dataset.clip];
  });
}

// Only one clip plays at a time, so comparisons stay honest.
document.addEventListener('play', function (e) {
  document.querySelectorAll('audio').forEach(function (a) {
    if (a !== e.target) { a.pause(); }
  });
}, true);

// Each part filters and sorts its own cards.
document.querySelectorAll('.part').forEach(function (part) {
  var list = part.querySelector('.cards');
  var original = Array.prototype.slice.call(part.querySelectorAll('.card'));
  var only = part.querySelector('[data-act="only"]');
  var sort = part.querySelector('[data-act="sort"]');

  only.addEventListener('click', function () {
    var on = only.getAttribute('aria-pressed') !== 'true';
    only.setAttribute('aria-pressed', on);
    original.forEach(function (c) {
      var w = parseFloat(c.dataset.wer);
      c.hidden = on && w === 0;
    });
  });

  sort.addEventListener('click', function () {
    var on = sort.getAttribute('aria-pressed') !== 'true';
    sort.setAttribute('aria-pressed', on);
    var cards = original.slice();
    if (on) {
      cards.sort(function (a, b) {
        var x = parseFloat(a.dataset.wer), y = parseFloat(b.dataset.wer);
        if (isNaN(x)) { x = Infinity; }
        if (isNaN(y)) { y = Infinity; }
        return y - x;
      });
    }
    cards.forEach(function (c) { list.appendChild(c); });
  });
});
"""


def controls() -> str:
    return ('<div class="controls">'
            '<button data-act="only" aria-pressed="false">uniquement les '
            'imparfaits</button>'
            '<button data-act="sort" aria-pressed="false">trier par WER</button>'
            "</div>")


LEGEND = ('<div class="legend">'
          '<span><span class="key sub">mot</span> substitué</span>'
          '<span><span class="key del">mot</span> omis</span>'
          '<span><span class="key ins">mot</span> inventé</span>'
          '<span>· signale l’absence d’un mot</span>'
          "</div>")


def build(data: dict) -> str:
    rows = data.get("rows", [])
    summary = data.get("summary", {})
    n = summary.get("n", len(rows))

    target = "fr"
    for row in rows:
        extra = [k for k in row if k not in RESERVED]
        if extra:
            target = extra[0]
            break

    stats = [
        ("énoncés testés", n),
        ("réponses parlées", f'{summary.get("tts_ok", 0)}/{n}'),
        ("WER aller-retour", pct(summary.get("corpus_wer_round_trip"))),
        ("WER relecture", pct(summary.get("corpus_wer_tts_roundtrip"))),
        ("WER reconnaissance", pct(summary.get("corpus_wer_real_audio"))),
        ("coût", f'${summary.get("estimated_usd", 0)}'),
    ]
    stat_html = "\n".join(
        f'<div class="stat"><b>{html.escape(str(v))}</b><span>{k}</span></div>'
        for k, v in stats)

    # Cards are built before the page so CLIPS is complete when it is written.
    reply_cards = "\n".join(reply_card(r, target) for r in rows)
    stt_cards = "\n".join(stt_card(r, target) for r in rows)

    clips_js = ""
    if EMBED and CLIPS:
        clips_js = f"<script>window.CLIPS={json.dumps(CLIPS)}</script>"

    provenance = (
        "Tous les extraits sont intégrés à ce fichier : il se lit hors ligne, "
        "sans rien d’autre à télécharger."
        if EMBED else
        "Les fichiers audio sont à côté de cette page, dans <code>stt/</code> "
        "(voix humaine, corpus ALFFA) et <code>tts/</code> (généré par "
        "Soynade) ; sans eux, les lecteurs restent muets."
    )

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Soynade en wolof — évaluation</title>
<style>{STYLE}</style>
</head>
<body>
<main>
<h1>Soynade en wolof — synthèse et reconnaissance</h1>
<p class="lede">
  Les deux sens de la conversation ont été testés séparément sur {n} phrases du
  corpus ALFFA : répondre en wolof à partir d’un texte français, et comprendre
  du wolof parlé. Chaque partie suit la même lecture — ce qui a été envoyé au
  modèle, le résultat attendu, puis sa réponse.
</p>

<div class="summary">{stat_html}</div>

<section class="about">
  <h2>Modèles et données</h2>
  <dl>
    <dt>Synthèse vocale</dt>
    <dd><a href="https://developers.soynade.ai/docs/models"><code>oolel-voices</code></a>
      — point d’entrée <code>/v1/text-to-speech</code>, voix par défaut.</dd>
    <dt>Reconnaissance et traduction</dt>
    <dd><a href="https://developers.soynade.ai/docs/models"><code>oolel-speech-v1</code></a>
      — points d’entrée <code>/v1/audio/transcriptions</code> et
      <code>/v1/translations</code>.</dd>
    <dt>Données de test</dt>
    <dd>
      <a href="https://github.com/getalp/ALFFA_PUBLIC">ALFFA</a>
      (<code>ASR/WOLOF/data/test</code>), corpus public de wolof lu : 846 phrases
      enregistrées par deux locuteurs, avec des transcriptions vérifiées par des
      experts. Aucune de ces phrases n’a été écrite pour ce test, et aucune ne
      provient de Soynade.
    </dd>
    <dt>Échantillon</dt>
    <dd>
      {n} phrases choisies de façon déterministe — celles de 5 à 14 mots, moitié
      du locuteur&nbsp;05, moitié du locuteur&nbsp;10. Échantillon court : à lire
      comme une indication, pas comme un classement.
    </dd>
  </dl>
</section>

<section class="part" id="reply">
  <header>
    <h2>1. Répondre — du français au wolof parlé</h2>
    <p class="what">
      C’est le chemin de la réponse : l’agent raisonne en français, et sa
      réponse doit revenir à l’utilisateur en wolof, à voix haute. Deux appels
      s’enchaînent — le texte français est traduit en wolof, puis ce wolof est
      lu par la synthèse vocale. Le français de départ est celui obtenu en
      partie 2, ce qui permet de comparer le wolof produit à la phrase
      d’origine : l’écart cumule donc la reconnaissance et les deux traductions,
      et non la seule synthèse.
    </p>
    <p class="flow"><b>texte {target}</b> → <b>/v1/translations</b> →
      <b>texte wolof</b> → <b>/v1/text-to-speech</b> → <b>audio wolof</b></p>
  </header>
  {LEGEND}
  {controls()}
  <div class="cards">
{reply_cards}
  </div>
</section>

<section class="part" id="stt">
  <header>
    <h2>2. Reconnaissance vocale — le modèle écoute</h2>
    <p class="what">
      On envoie un enregistrement humain, le modèle doit écrire ce qui est dit.
      Le résultat attendu est la transcription établie par un humain. Le
      <b>WER</b> (taux d’erreur sur les mots) compte les corrections nécessaires
      pour passer de la réponse à l’attendu, divisées par le nombre de mots
      attendus : 0 % est parfait.
    </p>
    <p class="flow"><b>audio wolof</b> → <b>/v1/audio/transcriptions</b> →
      <b>texte wolof</b> → <b>/v1/translations</b> → <b>texte {target}</b></p>
  </header>
  {LEGEND}
  {controls()}
  <div class="cards">
{stt_cards}
  </div>
</section>

<footer>
  Mesures réalisées sur le corpus de test
  <a href="https://github.com/getalp/ALFFA_PUBLIC">ALFFA Wolof</a>
  (enregistrements réels, transcriptions vérifiées par des humains).
  {provenance}
</footer>
</main>
{clips_js}
<script>{SCRIPT}</script>
</body>
</html>
"""


def main() -> int:
    global EMBED

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--embed", action="store_true",
                    help="carry the audio inside the page, as one file to send")
    ap.add_argument("-o", "--out", default=None,
                    help="output file (default report.html, "
                         "or report-shareable.html with --embed)")
    args = ap.parse_args()
    EMBED = args.embed

    source = OUT / "results.json"
    if not source.exists():
        sys.exit(f"No {source.relative_to(REPO)} — run scripts/soynade_eval.py first")

    data = json.loads(source.read_text(encoding="utf-8"))
    name = args.out or ("report-shareable.html" if EMBED else "report.html")
    page = OUT / name
    page.write_text(build(data), encoding="utf-8")

    rows = data.get("rows", [])
    human = sum(1 for r in rows if (OUT / "stt" / f'{r["id"]}.wav').exists())
    synthetic = sum(1 for r in rows if (OUT / "tts" / f'{r["id"]}.wav').exists())
    size = page.stat().st_size / 1e6
    print(f"wrote {page.relative_to(REPO)} — {len(rows)} utterances, "
          f"{human} human clips, {synthetic} synthetic")
    print(f"size: {size:.1f} MB" + (" (audio embedded, nothing else to send)"
                                    if EMBED else " (audio kept alongside)"))
    if EMBED and size > 20:
        print("warning: many mail services refuse attachments above ~20 MB")
    print(f"open it with:  xdg-open {page.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
