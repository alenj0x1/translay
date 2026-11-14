"""El resumen completo de un video, con el motor del agente (vt/llm.py: GPU, gráfica integrada o CPU).

Lo que sale (se guarda en la transcripción como `summary`, versión 2):
  overview      de qué se trató, en dos o tres párrafos
  chapters      capítulos [{t, title, points: [{t, text}]}]: la estructura del video con sus minutos
  points        todos los puntos en orden (los mismos de los capítulos; lo que ya usaban la vista,
                la exportación y la API)
  terms         conceptos clave [{term, meaning, t}]
  takeaways     ideas para llevarse
  resources     lo que aparece escrito y conviene tener a mano [{kind, text, t}] (enlaces, comandos,
                código), sacado del texto en pantalla (vt/videocontext.py), sin modelo
  suggestions   preguntas para el agente según el video: se guardan con el resumen, así están aunque el
                agente esté apagado (al tocar una, se enciende)

Cómo (piezas propias): la transcripción se corta en tramos que entran en el presupuesto del modelo del
equipo; de cada tramo salen sus secciones, puntos y conceptos en JSON con esquema obligatorio (llama.cpp
lo cumple con una gramática: hasta un modelo chico entrega la estructura completa). Los minutos se ajustan
al de una frase real del tramo. Con los capítulos se escribe el panorama, las ideas y las sugerencias.
"""

from __future__ import annotations

import json
import re
import time

from . import langs
from .videocontext import elements, stamp

_TIME = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")

SECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {"type": "array", "minItems": 1, "maxItems": 3, "items": {
            "type": "object",
            "properties": {
                "t": {"type": "string", "maxLength": 8}, "title": {"type": "string", "maxLength": 80},
                "points": {"type": "array", "minItems": 1, "maxItems": 6, "items": {
                    "type": "object", "properties": {"t": {"type": "string", "maxLength": 8},
                                                     "text": {"type": "string", "maxLength": 260}},
                    "required": ["t", "text"]}},
            },
            "required": ["t", "title", "points"]}},
        "terms": {"type": "array", "maxItems": 6, "items": {
            "type": "object", "properties": {"term": {"type": "string", "maxLength": 60},
                                             "meaning": {"type": "string", "maxLength": 200},
                                             "t": {"type": "string", "maxLength": 8}},
            "required": ["term", "meaning", "t"]}},
    },
    "required": ["sections", "terms"],
}
FINAL_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {"type": "string", "maxLength": 1600},
        "takeaways": {"type": "array", "minItems": 2, "maxItems": 6, "items": {"type": "string", "maxLength": 220}},
        "suggestions": {"type": "array", "minItems": 3, "maxItems": 5, "items": {"type": "string", "maxLength": 120}},
    },
    "required": ["overview", "takeaways", "suggestions"],
}

# en inglés con la orden de escribir en el idioma de la app (tools/lab/lang_adherence.py)
SECTION_SYSTEM = """You summarize one part of a video for a reader of {language}. You get the transcript of that part with the minute of each sentence ([m:ss]) and, when there is any, what is written on screen.
Return:
- sections: 1 to 4 sections of this part, in order. Each one with the minute where it starts (t, like "3:15"), a short title and its important points: each point is a complete, concrete sentence in your own words (don't copy sentences from the transcript), with the data, names, examples or commands that matter, and the minute where it is said.
- terms: the key concepts or terms of this part, with a short explanation and their minute. If there are none, an empty list.
Write every title, point and explanation in {language}, whatever the language of the video. Use only what is in the material; don't invent."""

FINAL_SYSTEM = """You write the closing of a video summary for a reader of {language}. You get the chapters with their points.
Return:
- overview: what the video was about in 2 or 3 short paragraphs: the topic, how it unfolds and where it lands.
- takeaways: 2 to 6 concrete ideas to take away (one sentence each).
- suggestions: 3 to 5 questions someone watching this video would want to ask an assistant about it (short, specific to this video, addressed to the assistant: "What…?", "Explain…").
Write everything in {language}. Use only what is in the chapters."""


def _lines(tr, screen: dict | None) -> list[tuple[float, str]]:
    """Las frases con su minuto (en el idioma original: los modelos lo entienden mejor) y lo escrito en
    pantalla en su momento."""
    names = tr.data.get("speaker_names") or {}
    order: dict = {}
    for s in tr.segments:
        if s.get("speaker") is not None and s["speaker"] not in order:
            order[s["speaker"]] = len(order) + 1
    out = []
    for s in sorted(tr.segments, key=lambda x: x["start"]):
        who = ""
        if len(order) > 1 and s.get("speaker") is not None:
            who = (names.get(str(s["speaker"])) or f"P{order[s['speaker']]}") + ": "
        out.append((s["start"], f"[{stamp(s['start'])}] {who}{s.get('text', '').strip()}"))
    for e in elements(screen):
        out.append((e["start"], f"[{stamp(e['start'])}] (on screen, {e['kind']}) {e['text'][:300]}"))
    return sorted(out, key=lambda x: x[0])


def _chunks(lines: list[tuple[float, str]], budget_chars: int) -> list[list[tuple[float, str]]]:
    out, cur, size = [], [], 0
    for t, s in lines:
        if cur and size + len(s) > budget_chars:
            out.append(cur)
            cur, size = [], 0
        cur.append((t, s))
        size += len(s) + 1
    if cur:
        # un último tramo muy corto se suma al anterior
        if out and size < budget_chars // 4:
            out[-1].extend(cur)
        else:
            out.append(cur)
    return out


def _locate(text: str, chunk: list[tuple[float, str]], match: dict) -> float | None:
    """El minuto de un punto por su contenido: la frase del tramo (original + traducción) con más palabras
    en común. Un modelo chico copia mal las horas; el contenido no miente."""
    from .agent import _terms

    q = set(_terms(text))
    if len(q) < 2:
        return None
    best, at = 1, None
    for t, _ in chunk:
        n = len(q & match.get(t, set()))
        if n > best:
            best, at = n, t
    return at


def _snap(value: str, chunk: list[tuple[float, str]], text: str = "", match: dict | None = None) -> float:
    """El minuto de un punto: por su contenido si se encuentra en el tramo; si no, el que dice el modelo,
    ajustado al de una frase real del tramo."""
    times = [t for t, _ in chunk]
    if text and match:
        at = _locate(text, chunk, match)
        if at is not None:
            return at
    m = _TIME.search(value or "")
    if not m:
        return times[0]
    a, b, c = m.groups()
    sec = int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)
    if sec < times[0] - 5 or sec > times[-1] + 30:
        return times[0]
    return min(times, key=lambda t: abs(t - sec))


def _json(text: str) -> dict:
    """El JSON del modelo; si se cortó al llegar al límite de tokens, lo que quedó completo."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    # reparar: se recorta hasta el último objeto cerrado y se cierran los corchetes abiertos
    for end in range(len(text), 0, -1):
        if text[end - 1] != "}":
            continue
        head = text[:end]
        stack = []
        in_str = esc = False
        for ch in head:
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]" and stack:
                stack.pop()
        if in_str:
            continue
        try:
            return json.loads(head + "".join(reversed(stack)))
        except ValueError:
            continue
    return {}


def summarize(srv, info: dict, tr, screen: dict | None, budget_tokens: int, progress=None,
              cancelled=lambda: False, model: str = "", lang: str | None = None) -> dict | None:
    """El resumen completo con un llm.Server ya cargado, en el idioma de la app (o `lang`). None si se canceló."""
    t0 = time.perf_counter()
    lang = lang or langs.ui()
    language = langs.PROMPT[lang]
    lines = _lines(tr, screen)
    from .agent import _terms

    # para ubicar cada punto: las palabras de cada frase en el original y en la traducción
    match: dict = {}
    for sg in tr.segments:
        match.setdefault(sg["start"], set()).update(_terms(f"{sg.get('text', '')} {sg.get('translation') or ''}"))
    if not lines:
        return {"version": 2, "overview": "", "chapters": [], "points": [], "terms": [], "takeaways": [],
                "resources": [], "suggestions": [], "model": model, "lang": lang, "created": time.time(),
                "seconds": 0.0, "empty": True}
    budget_chars = int(max(1200, min(9000, budget_tokens // 2)) * 3.6)
    cs = _chunks(lines, budget_chars)
    total = len(cs) + 1
    chapters, terms = [], []
    title = info.get("title") or ""
    for i, c in enumerate(cs):
        if cancelled():
            return None
        if progress:
            progress(i, total)
        user = (f"Video: {title}\nPart {i + 1} of {len(cs)}\n\n" if title else f"Part {i + 1} of {len(cs)}\n\n") \
            + "\n".join(s for _, s in c) + f"\n\n(Write in {language}.)"
        r = srv.chat([{"role": "system", "content": SECTION_SYSTEM.format(language=language)},
                      {"role": "user", "content": user}],
                     max_tokens=2600, temperature=0.2, chat_template_kwargs={"enable_thinking": False},
                     response_format={"type": "json_schema", "json_schema": {"schema": SECTION_SCHEMA}})
        d = _json(r["text"])
        for sec in d.get("sections", []):
            pts = [{"t": _snap(p.get("t", ""), c, p["text"], match), "text": p["text"].strip()}
                   for p in sec.get("points", []) if p.get("text", "").strip()]
            if pts:
                pts.sort(key=lambda p: p["t"])
                # la sección empieza con su primer punto (más confiable que la hora que escribió el modelo)
                chapters.append({"t": pts[0]["t"], "title": sec.get("title", "").strip(), "points": pts})
        for x in d.get("terms", []):
            if x.get("term", "").strip() and x.get("meaning", "").strip():
                terms.append({"term": x["term"].strip(), "meaning": x["meaning"].strip(),
                              "t": _snap(x.get("t", ""), c, x["term"] + " " + x["meaning"], match)})
    if cancelled():
        return None
    if progress:
        progress(total - 1, total)
    chapters.sort(key=lambda c: c["t"])
    # el cierre: con los capítulos (títulos y puntos) que entran en el presupuesto
    outline, size = [], 0
    for ch in chapters:
        block = f"## [{stamp(ch['t'])}] {ch['title']}\n" + "\n".join(f"- {p['text']}" for p in ch["points"])
        if size + len(block) > budget_chars * 1.5:
            block = f"## [{stamp(ch['t'])}] {ch['title']}"
        outline.append(block)
        size += len(block)
    r = srv.chat([{"role": "system", "content": FINAL_SYSTEM.format(language=language)},
                  {"role": "user", "content": (f"Video: {title}\n\n" if title else "") + "\n\n".join(outline)
                   + f"\n\n(Write in {language}.)"}],
                 max_tokens=1200, temperature=0.3, chat_template_kwargs={"enable_thinking": False},
                 response_format={"type": "json_schema", "json_schema": {"schema": FINAL_SCHEMA}})
    fin = _json(r["text"])
    seen, uniq_terms = set(), []
    for x in terms:
        k = x["term"].lower()
        if k not in seen:
            seen.add(k)
            uniq_terms.append(x)
    resources = [{"kind": e["kind"], "text": e["text"], "t": e["start"]} for e in elements(screen)
                 if e["kind"] in ("link", "command", "code", "email", "handle")][:40]
    if progress:
        progress(total, total)
    return {"version": 2, "overview": (fin.get("overview") or "").strip(), "chapters": chapters,
            "points": [p for ch in chapters for p in ch["points"]], "terms": uniq_terms[:20],
            "takeaways": [x.strip() for x in fin.get("takeaways", []) if x.strip()],
            "resources": resources, "suggestions": [x.strip() for x in fin.get("suggestions", []) if x.strip()][:5],
            "model": model, "lang": lang, "created": time.time(), "seconds": round(time.perf_counter() - t0, 1)}


def as_text(title: str, s: dict) -> str:
    """El resumen completo como texto (exportar, copiar)."""
    out = [title, "", "Resumen", "", (s.get("overview") or "").strip(), ""]
    if s.get("takeaways"):
        out += ["Ideas clave", ""] + [f"- {x}" for x in s["takeaways"]] + [""]
    for ch in s.get("chapters") or []:
        out += [f"[{stamp(ch['t'])}] {ch['title']}"] + [f"  [{stamp(p['t'])}] {p['text']}" for p in ch["points"]] + [""]
    if not s.get("chapters") and s.get("points"):
        out += ["Puntos importantes", ""] + [f"[{stamp(p['t'])}] {p['text']}" for p in s["points"]] + [""]
    if s.get("terms"):
        out += ["Conceptos clave", ""] + [f"- {x['term']}: {x['meaning']} [{stamp(x['t'])}]" for x in s["terms"]] + [""]
    if s.get("resources"):
        out += ["Recursos del video", ""] + [f"[{stamp(x['t'])}] {x['text']}" for x in s["resources"]] + [""]
    return "\n".join(out) + "\n"
