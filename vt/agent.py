"""El agente de cada video: conversar con todo lo que se sabe de él (lo que se dice y lo que se ve).

  context(...)        lo que el modelo lee del video: entero si entra en su presupuesto de tokens; si no
                      (equipos chicos), el resumen, el tramo donde va la persona y los fragmentos que más
                      se parecen a la pregunta (búsqueda propia por palabras, sobre la traducción y el original)
  messages(...)       la conversación para el modelo: instrucciones (con el tono y el nombre que elige la
                      persona), el contexto primero (se reutiliza entre preguntas: caché del servidor) y al
                      final la posición y la pregunta
  suggestions(...)    preguntas sugeridas según el video (sin modelo: por lo que contiene)
  stamps(text)        los [m:ss] de una respuesta, para volverlos enlaces al momento

Las horas van como [m:ss] (vt/videocontext.py) y el modelo las cita igual.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from . import langs
from .videocontext import elements, markdown, stamp

CHARS_PER_TOKEN = 3.6     # español e inglés con los tokenizadores de estos modelos (medido en el laboratorio)
CHUNK_S = 45.0            # fragmentos para la búsqueda
DEFAULT_NAME = "Translay"

# en inglés (los modelos siguen mejor las instrucciones así) con la orden de responder en el idioma de la app;
# medido con tools/lab/lang_adherence.py
SYSTEM = """You are {name}, the assistant for one video inside Translay. You answer questions about THIS video using only the material below (timestamped transcript, translation, text shown on screen, the summary and the person's notes).

Rules:
- Always answer in {language}, whatever the language of the video or of the question; clear and direct, in your own words (don't copy the transcript).
- Every fact taken from the video carries its moment in square brackets, as in the material. Example: "He uses a coffee subscription as an example [1:04] and offers a 30-day trial [1:22]."
- If the video doesn't say it, answer that the video doesn't mention it; never invent facts, names or times.
- Code, commands and links stay exactly as written, in code blocks when it fits.
- If the person asks what's left, tell them what comes after the point they're at, with its moments.{tone}"""

_WORD = re.compile(r"[^\W_]+", re.U)
_STOP = set("""a al algo como con cual cuando de del donde el ella en es esa ese eso esta este esto fue ha hay la las
le lo los me mi muy no o para pero por que qué se ser si sin sobre su sus te tu un una uno y ya the a an and are as at be
by for from has have in is it its of on or that the this to was were what when where which who why will with you your
video dice explica habla qué cómo cuál cuándo dónde quién""".split())


def tokens_estimate(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def _terms(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(text.lower()):
        if w in _STOP or len(w) < 3:
            continue
        out.append(w[:6])  # raíz corta: «configuración» y «configurar» se encuentran
    return out


def chunks(tr, screen: dict | None = None, size: float = CHUNK_S) -> list[dict]:
    """Fragmentos de ~45 s: [{start, end, text}] con el original, la traducción y lo escrito en pantalla
    en ese tramo."""
    segs = sorted(tr.segments, key=lambda s: s["start"])
    els = elements(screen)
    out, cur = [], None
    for s in segs:
        if cur is None or s["start"] - cur["start"] >= size:
            cur = {"start": s["start"], "end": s["end"], "lines": []}
            out.append(cur)
        cur["end"] = s["end"]
        line = f"[{stamp(s['start'])}] {s.get('text', '').strip()}"
        if tr.translates and s.get("translation"):
            line += f"\n  → {s['translation'].strip()}"
        cur["lines"].append(line)
    for e in els:
        c = next((c for c in out if c["start"] <= e["start"] <= c["end"] + size), None)
        if c:
            c["lines"].append(f"[{stamp(e['start'])}] (on screen) {e['text']}")
    for c in out:
        c["text"] = "\n".join(c["lines"])
    return out


def search(parts: list[dict], query: str, k: int = 8) -> list[dict]:
    """BM25 sobre los fragmentos (original + traducción): los k que más se parecen a la pregunta."""
    q = _terms(query)
    if not q or not parts:
        return []
    docs = [Counter(_terms(p["text"])) for p in parts]
    n = len(docs)
    avg = sum(sum(d.values()) for d in docs) / n
    df = Counter(t for d in docs for t in set(d))
    scores = []
    for i, d in enumerate(docs):
        L = sum(d.values()) or 1
        s = 0.0
        for t in set(q):
            if t in d:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * d[t] * 2.2 / (d[t] + 1.2 * (0.25 + 0.75 * L / avg))
        scores.append((s, i))
    best = [i for s, i in sorted(scores, reverse=True)[:k] if s > 0]
    return [parts[i] for i in sorted(best)]


def context(info: dict, tr, screen: dict | None, question: str = "", position: float | None = None,
            budget: int = 6000) -> tuple[str, str]:
    """(texto, modo): «completo» si todo el video entra en `budget` tokens; si no, «fragmentos»."""
    full = markdown(info, tr, screen, None)
    if tokens_estimate(full) <= budget:
        return full, "completo"
    parts = chunks(tr, screen)
    head = [f"# {info.get('title') or tr.data.get('name') or ''}".strip()]
    if info.get("duration"):
        head.append(f"Duration: {stamp(info['duration'])}")
    summary = tr.data.get("summary")
    if summary:
        head += ["", "## Summary", summary.get("overview", "").strip()]
        head += [f"- [{stamp(p.get('t', 0))}] {p.get('text', '').strip()}" for p in summary.get("points", [])]
    text = "\n".join(head)
    left = budget - tokens_estimate(text) - 50
    chosen: list[dict] = []
    near = [p for p in parts if position is not None and p["start"] - 60 <= position <= p["end"] + 30]
    q = set(_terms(question))
    for p in near + search(parts, question, k=12):
        if p in chosen:
            continue
        cost = tokens_estimate(p["text"])
        if cost > left:
            # no entra entero (equipos con poca memoria): sus renglones que más se parecen a la pregunta
            lines = sorted(p["lines"], key=lambda ln: -len(q & set(_terms(ln))))
            keep = []
            for ln in lines:
                c = tokens_estimate(ln)
                if c <= left and (q & set(_terms(ln)) or not keep):
                    keep.append(ln)
                    left -= c
            if keep:
                chosen.append({"start": p["start"], "text": "\n".join(ln for ln in p["lines"] if ln in keep)})
            continue
        chosen.append(p)
        left -= cost
    chosen.sort(key=lambda p: p["start"])
    body = "\n\n".join(p["text"] for p in chosen)
    return (f"{text}\n\n## Related parts of the video (not the full transcript)\n\n{body}\n",
            "fragmentos")


def messages(info: dict, tr, screen: dict | None, question: str, history: list[dict] | None = None,
             position: float | None = None, budget: int = 6000, name: str = "", tone: str = "",
             lang: str | None = None) -> tuple[list, str]:
    """Mensajes para el modelo. El contexto va primero y sin la posición (así el servidor reutiliza lo
    ya procesado entre preguntas); la posición y la pregunta, al final. lang: idioma de la respuesta
    (por defecto, el de la app)."""
    ctx, mode = context(info, tr, screen, question + " " + " ".join(h["content"] for h in (history or [])[-2:]),
                        position, budget)
    tone = tone.strip()
    system = SYSTEM.format(name=name.strip() or DEFAULT_NAME, language=langs.PROMPT[lang or langs.ui()],
                           tone=f"\n\nHow to answer (the person asked for this): {tone}" if tone else "")
    msgs = [{"role": "system", "content": f"{system}\n\n---\n\n{ctx}"}]
    msgs += [{"role": h["role"], "content": h["content"]} for h in (history or [])[-6:]]
    # sin corchetes: con ellos el modelo la copiaba al comienzo de la respuesta como si fuera una cita
    where = f"(The person is at minute {stamp(position)} of the video.)\n" if position is not None else ""
    # el idioma, también al final: los modelos chicos siguen el idioma de la pregunta más que el de las instrucciones
    # (tools/lab/lang_adherence.py: pidiendo inglés con la pregunta en español, 0 de 5 sin este recordatorio)
    msgs.append({"role": "user", "content": f"{where}{question}\n\n(Answer in {langs.PROMPT[lang or langs.ui()]}.)"})
    return msgs, mode


_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


def clean(text: str) -> str:
    """La respuesta sin el razonamiento oculto que algunos modelos escriben (<think>…</think>)."""
    return _THINK.sub("", text).strip()


_SENT = re.compile(r"[^.!?\n]+[.!?]*", re.U)


def cite(answer: str, tr, screen: dict | None = None, min_score: float = 4.0) -> str:
    """Citas propias: a cada frase de la respuesta que no trae su momento se le agrega el [m:ss] del
    tramo del video que más se le parece (búsqueda por palabras sobre la traducción y el original).
    Así cita bien hasta un modelo chico, que casi nunca escribe las horas solo. Una frase que no se
    parece a nada del video (un saludo, una conclusión propia) queda sin cita."""
    segs = sorted(tr.segments, key=lambda s: s["start"])
    if not segs or not answer.strip():
        return answer
    # unidades de dos frases seguidas: una idea suele cruzar el corte de una frase
    units = [{"start": a["start"], "pair": (a, b), "text": f"{a.get('text', '')} {a.get('translation') or ''} "
                                                          f"{b.get('text', '')} {b.get('translation') or ''}"}
             for a, b in zip(segs, segs[1:] + segs[-1:])]
    for e in elements(screen):
        units.append({"start": e["start"], "text": e["text"] + " " + (e.get("translation") or "")})
    docs = [Counter(_terms(u["text"])) for u in units]
    n = len(docs)
    avg = sum(sum(d.values()) for d in docs) / n or 1
    df = Counter(t for d in docs for t in set(d))
    out, in_code = [], False
    for line in answer.split("\n"):
        if line.strip().startswith("```"):
            in_code = not in_code
        if in_code or line.strip().startswith("```") or _STAMP.search(line):
            out.append(line)
            continue
        pieces = []
        for m in _SENT.finditer(line):
            s = m.group(0)
            q = set(_terms(s))
            if len(q) < 3:
                pieces.append(s)
                continue
            def score(d):
                L = sum(d.values()) or 1
                return sum(math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) * d[t] * 2.2 / (d[t] + 1.2 * (0.25 + 0.75 * L / avg))
                           for t in q if t in d)
            best, at, win = 0.0, None, None
            for d, u in zip(docs, units):
                sc = score(d)
                if sc > best:
                    best, at, win = sc, u["start"], u
            if win and win.get("pair"):  # del par, la frase que más se parece (lo dicho puede estar en la segunda)
                a, b = win["pair"]
                sa, sb = (score(Counter(_terms(f"{x.get('text', '')} {x.get('translation') or ''}"))) for x in (a, b))
                at = b["start"] if sb > sa else a["start"]
            if at is not None and best >= min_score:
                end = len(s.rstrip()) - len(s.rstrip().rstrip(".!?"))
                core = s.rstrip()[:len(s.rstrip()) - end] if end else s.rstrip()
                s = f"{core} [{stamp(at)}]{s.rstrip()[len(core):]}{s[len(s.rstrip()):]}"
            pieces.append(s)
        out.append("".join(pieces) if pieces else line)
    return "\n".join(out)


_STAMP = re.compile(r"\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]")


def stamps(text: str) -> list[float]:
    out = []
    for m in _STAMP.finditer(text):
        a, b, c = m.groups()
        out.append(int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b))
    return out


def suggestions(info: dict, tr, screen: dict | None, position: float | None = None, n: int = 4) -> list[dict]:
    """Sugerencias según lo que tiene el video (sin modelo: al instante): [{q, action?}]. «summary» pide
    el resumen de la app (vt/summaries.py), con sus puntos y minutos."""
    els = elements(screen)
    kinds = Counter(e["kind"] for e in els)
    dur = float(info.get("duration") or 0)
    out = []
    lead = []
    if not tr.data.get("summary") and tr.segments:
        lead.append({"q": "Generar el resumen del video", "action": "summary"})
    if position and dur and 0.1 < position / dur < 0.9:
        out.append("¿Qué me falta por ver desde donde voy?")
    if kinds["command"]:
        out.append("¿Qué comandos se usan y para qué sirve cada uno?")
    if kinds["code"]:
        e = next(e for e in els if e["kind"] == "code")
        out.append(f"Explícame el código que aparece en [{stamp(e['start'])}]")
    if kinds["link"]:
        out.append("¿Qué enlaces o recursos menciona el video?")
    speakers = {s.get("speaker") for s in tr.segments if s.get("speaker") is not None}
    if len(speakers) > 1:
        out.append("¿Qué opina cada persona que habla?")
    out += ["¿Cuáles son las ideas principales?", "Dame 3 preguntas para repasar lo que vi",
            "¿Qué términos técnicos se usan y qué significan?"]
    seen, final = set(), []
    for q in out:
        if q not in seen:
            seen.add(q)
            final.append({"q": q})
    return (lead + final)[:n]


# ------------------------------------------------------------------ descripción corta (bajo el título)
DESCRIBE_CHARS = 6000  # lo que lee el modelo chico: el inicio y tramos repartidos por todo el video


def describe_messages(info: dict, tr, lang: str | None = None) -> list[dict]:
    """El pedido de la descripción corta: una o dos frases que digan de qué trata el video, en el idioma
    de la app (o `lang`)."""
    lines = [(s.get("translation") or s.get("text") or "").strip() for s in tr.segments]
    lines = [x for x in lines if x]
    body = " ".join(lines)
    if len(body) > DESCRIBE_CHARS:  # mitad del inicio (de qué trata) y mitad repartida (hacia dónde va)
        head, rest, picked = [], [], 0
        for x in lines:
            if picked > DESCRIBE_CHARS // 2:
                break
            head.append(x)
            picked += len(x) + 1
        tail = lines[len(head):]
        step = max(1, len(tail) * 120 // (DESCRIBE_CHARS // 2) or 1)
        rest = tail[::step]
        body = " ".join(head) + " […] " + " ".join(rest)
        body = body[:DESCRIBE_CHARS + 400]
    language = langs.PROMPT[lang or langs.ui()]
    system = (f"You write the description of a video for a library: one or two sentences in {language}, no longer "
              "than 220 characters, saying what it is about and what the viewer learns. Third person, neutral and "
              "professional tone. No quotation marks, no emojis, don't start with \"In this video\" or \"The video\" "
              "(in any language), don't invent facts that are not in the transcript. Reply only with the "
              f"description, written in {language}.")
    user = (f"Title: {info.get('title') or tr.data.get('name') or ''}\n\nTranscript:\n{body}\n\n"
            f"Write the description in {language}.")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


_LEAD = re.compile(r"^\s*(descripci[oó]n|resumen|description|summary|descri[cç][aã]o|resumo)\s*:\s*", re.I)
_VIDEO_START = re.compile(r"^((en )?(este|el) video|(in )?this video|the video|(neste|este|o) v[ií]deo),?\s+", re.I)


def clean_description(text: str, limit: int = 260) -> str:
    """La descripción lista para mostrar: sin razonamiento, rótulos ni comillas, y cortada en una frase."""
    t = " ".join(clean(text).split())
    t = _LEAD.sub("", t).strip(" \"'«»“”")
    t = _VIDEO_START.sub("", t)
    t = t[:1].upper() + t[1:]
    if len(t) > limit:
        cut = max(t.rfind(". ", 0, limit), t.rfind("? ", 0, limit), t.rfind("! ", 0, limit))
        t = t[:cut + 1] if cut > 60 else t[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    if t and t[-1] not in ".!?…":
        t += "."
    return t


def first_sentences(text: str, limit: int = 240) -> str:
    """Las primeras frases de un texto largo (la visión general del resumen) que caben en limit."""
    out = ""
    for s in re.findall(r"[^.!?]+[.!?]+", " ".join(text.split())):
        if out and len(out) + len(s) > limit:
            break
        out += s
    return clean_description(out.strip() or text, limit)
