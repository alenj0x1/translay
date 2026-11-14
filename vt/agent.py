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

from .videocontext import elements, markdown, stamp

CHARS_PER_TOKEN = 3.6     # español e inglés con los tokenizadores de estos modelos (medido en el laboratorio)
CHUNK_S = 45.0            # fragmentos para la búsqueda
DEFAULT_NAME = "Translay"

SYSTEM = """Eres {name}, el asistente de un video dentro de Translay. Respondes preguntas sobre ESTE video usando solo lo que está en el material que te doy (transcripción con horas, traducción, lo escrito en pantalla, el resumen y las notas de la persona).

Reglas:
- Responde en español latinoamericano, claro y directo, con tus palabras (no copies la transcripción).
- Cada dato que sale del video lleva el momento entre corchetes, como en el material. Ejemplo: «Usa una suscripción de café como ejemplo [1:04] y ofrece una prueba de 30 días [1:22].»
- Si el video no lo dice, responde que el video no lo menciona; no inventes datos, nombres ni horas.
- El código, los comandos y los enlaces van tal cual, en bloques de código cuando corresponda.
- Si la persona pregunta qué le falta, cuéntale lo que viene después de donde va, con sus momentos.{tone}"""

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
            c["lines"].append(f"[{stamp(e['start'])}] (en pantalla) {e['text']}")
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
        head.append(f"Duración: {stamp(info['duration'])}")
    summary = tr.data.get("summary")
    if summary:
        head += ["", "## Resumen", summary.get("overview", "").strip()]
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
    return (f"{text}\n\n## Partes del video relacionadas (no es la transcripción completa)\n\n{body}\n",
            "fragmentos")


def messages(info: dict, tr, screen: dict | None, question: str, history: list[dict] | None = None,
             position: float | None = None, budget: int = 6000, name: str = "", tone: str = "") -> tuple[list, str]:
    """Mensajes para el modelo. El contexto va primero y sin la posición (así el servidor reutiliza lo
    ya procesado entre preguntas); la posición y la pregunta, al final."""
    ctx, mode = context(info, tr, screen, question + " " + " ".join(h["content"] for h in (history or [])[-2:]),
                        position, budget)
    tone = tone.strip()
    system = SYSTEM.format(name=name.strip() or DEFAULT_NAME,
                           tone=f"\n\nCómo responder (lo pidió la persona): {tone}" if tone else "")
    msgs = [{"role": "system", "content": f"{system}\n\n---\n\n{ctx}"}]
    msgs += [{"role": h["role"], "content": h["content"]} for h in (history or [])[-6:]]
    # sin corchetes: con ellos el modelo la copiaba al comienzo de la respuesta como si fuera una cita
    where = f"(La persona va en el minuto {stamp(position)} del video.)\n" if position is not None else ""
    msgs.append({"role": "user", "content": f"{where}{question}"})
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


def describe_messages(info: dict, tr) -> list[dict]:
    """El pedido de la descripción corta: una o dos frases que digan de qué trata el video."""
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
    system = ("Escribes la descripción de un video para una biblioteca: una o dos frases en español, de no más de "
              "220 caracteres, que digan de qué trata y qué aprende quien lo vea. Tercera persona, tono neutro y "
              "profesional. Sin comillas, sin emojis, sin «En este video» ni «El video» al comienzo, sin inventar "
              "datos que no estén en la transcripción. Responde solo con la descripción.")
    user = f"Título: {info.get('title') or tr.data.get('name') or ''}\n\nTranscripción (traducida):\n{body}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


_LEAD = re.compile(r"^\s*(descripci[oó]n|resumen)\s*:\s*", re.I)
_VIDEO_START = re.compile(r"^(en )?(este|el) video,?\s+", re.I)


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
