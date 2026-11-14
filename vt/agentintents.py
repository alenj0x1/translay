"""Acciones del agente: pedidos que no necesitan al modelo y que la app resuelve al instante (también con el
agente apagado), cada uno con su tarjeta en la conversación.

    exportar   «exporta esto para Claude», «pásalo a ChatGPT»     → tarjeta con el video en Markdown (copiar, .md)
    ir a       «llévame al minuto 3:15», «ve a donde explica X»   → salta ahí; tarjeta con el momento
    subtítulos «pon los subtítulos en inglés», «quita los subtítulos»
    guardar    «guarda este video en Python»                      → lo agrega a esa colección
    avisos     «avísame cuando hablen de precios»                 → marca esos momentos y avisa al llegar

route() devuelve {text, card?, action?} o None (entonces responde el modelo, vt/agentsvc.py). La tarjeta y la
acción viajan con el mensaje (agent_done) y se guardan en la conversación; la acción la ejecuta la vista.
"""

from __future__ import annotations

import re

from . import agent
from .videocontext import markdown, stamp

_EXPORT = re.compile(r"\b(export\w*|p[aá]s\w*|ll[eé]v\w*|c[oó]pi\w*|m[aá]nd\w*|env[ií]\w*|s[aá]c\w*|prep[aá]r\w*)\b.*\b(claude|chat\s?gpt|gpt|gemini|"
                     r"copilot|un agente|otro agente|agente|ia|notion|obsidian|markdown|md)\b", re.I | re.S)
_EXPORT_FOR = re.compile(r"\bpara\s+(claude|chat\s?gpt|gemini|copilot|notion|obsidian)\b", re.I)
_TARGETS = {"claude": "Claude", "chatgpt": "ChatGPT", "chat gpt": "ChatGPT", "gpt": "ChatGPT", "gemini": "Gemini",
            "copilot": "Copilot", "notion": "Notion", "obsidian": "Obsidian"}
_SEEK = re.compile(r"^\s*(ll[eé]vame|ve\b|vamos|ir\b|salta|p[oó]nlo|pon el video|reproduce|repite|regresa|vuelve|mu[eé]strame "
                   r"(el|la) (momento|parte))", re.I)
_TIME = re.compile(r"\b(?:(\d{1,2}):(\d{2})(?::(\d{2}))?|minuto\s+(\d{1,3})(?:\s*(?:y|con)\s*(\d{1,2})\s*segundos?)?)\b", re.I)
_SUBS = re.compile(r"\bsubt[ií]tulos?\b", re.I)
_SAVE = re.compile(r"^\s*(guarda|gu[aá]rdalo|agrega|agr[eé]galo|a[nñ]ade|a[nñ][aá]delo|mete|m[eé]telo)\b(?:\s+(?:este|el)\s+video)?"
                   r"\s+(?:en|a)\s+(?:la\s+colecci[oó]n\s+|mi\s+colecci[oó]n\s+)?[«\"']?(.+?)[»\"']?\s*\.?\s*$", re.I)
_ALERT = re.compile(r"\b(av[ií]same|avisa|al[eé]rtame|marca|m[aá]rcame|notif[ií]came)\b.*?\b(cuando|donde|si|en qu[eé])\b\s*"
                    r"(?:se\s+)?(?:hablen|habla|hable|digan|dice|diga|mencionen|menciona|mencione|aparezca|aparece|expliquen|explica|explique|"
                    r"toquen|toca|trate|tratan|trata)?\s*(?:de|del|sobre|acerca de|la|el|los|las)?\s*(.+?)\s*\.?\s*$", re.I | re.S)


def _parts(tr) -> list[dict]:
    """Cada frase como fragmento para buscar (original + traducción)."""
    return [{"start": s["start"], "end": s["end"], "text": f"{s.get('text', '')} {s.get('translation') or ''}",
             "es": (s.get("translation") or s.get("text") or "").strip()} for s in tr.segments]


def _when(question: str) -> float | None:
    # primero una hora escrita (1:35); si no, «minuto 3»
    hm = re.search(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b", question)
    if hm:
        a, b, c = hm.groups()
        return int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)
    m = _TIME.search(question)
    if not m:
        return None
    a, b, c, mins, secs = m.groups()
    if mins:
        return int(mins) * 60 + int(secs or 0)
    return int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)


def route(question: str, info: dict, tr, screen: dict | None, position: float | None) -> dict | None:
    q = question.strip()
    if not q:
        return None

    # exportar el video para otro agente
    m = _EXPORT_FOR.search(q) or (_EXPORT.search(q) if len(q) < 160 else None)
    if m:
        target = next((name for key, name in _TARGETS.items() if re.search(rf"\b{key}\b", q, re.I)), "")
        content = markdown(info, tr, screen, position)
        title = f"Para pegar en {target}" if target else "Para pegar en un agente"
        return {"text": f"Listo: el video completo en Markdown, con sus tiempos, la traducción y lo que aparece en pantalla{', listo para ' + target if target else ''}.",
                "card": {"type": "export", "title": title, "target": target, "content": content,
                         "file": re.sub(r"[^\w-]+", "-", (info.get("title") or tr.data.get("name") or "video").strip())[:60] + ".md"}}

    # avisos mientras ves
    m = _ALERT.search(q)
    if m and m.group(3).strip():
        topic = re.sub(r"^(de|del|sobre)\s+", "", m.group(3).strip(), flags=re.I)
        hits = agent.search(_parts(tr), topic, k=8)
        times = [{"t": round(h["start"], 2), "text": h["es"][:160]} for h in hits]
        if not times:
            return {"text": f"No encontré momentos donde se hable de «{topic}» en este video."}
        return {"text": (f"Te aviso al llegar al momento donde se habla de «{topic}». Lo marqué en la barra de avance."
                         if len(times) == 1 else
                         f"Te aviso al llegar a los {len(times)} momentos donde se habla de «{topic}». Los marqué en la barra de avance."),
                "card": {"type": "alert", "topic": topic, "times": times}, "action": {"type": "alert", "topic": topic, "times": times}}

    # subtítulos
    if _SUBS.search(q) and re.search(r"\b(pon|activa|muestra|cambia|quita|apaga|oculta|desactiva|sin)\b", q, re.I):
        if re.search(r"\b(quita|apaga|oculta|desactiva|sin)\b", q, re.I):
            return {"text": "Listo: subtítulos desactivados.", "action": {"type": "subs", "value": "off"}}
        lang = "en" if re.search(r"\b(ingl[eé]s|original|english)\b", q, re.I) else "es"
        return {"text": f"Listo: subtítulos en {'inglés' if lang == 'en' else 'español'}.", "action": {"type": "subs", "value": lang}}

    # guardar en una colección
    m = _SAVE.search(q)
    if m and len(m.group(2)) <= 60:
        name = m.group(2).strip(" .»\"'")
        return {"text": f"Lo guardo en «{name}».", "action": {"type": "save", "collection": name}}

    # ir a un momento
    if _SEEK.search(q):
        t = _when(q)
        if t is not None:
            seg = min(tr.segments, key=lambda s: abs(s["start"] - t), default=None)
            text = ((seg.get("translation") or seg.get("text") or "").strip() if seg else "")[:180]
            return {"text": f"Vamos a [{stamp(t)}].", "card": {"type": "moment", "t": t, "text": text},
                    "action": {"type": "seek", "t": t}}
        topic = re.sub(_SEEK, "", q).strip()
        topic = re.sub(r"^(a|al|hasta|donde|la parte|el momento|en que|en qué|cuando)\s+", "", topic, flags=re.I)
        hit = agent.search(_parts(tr), topic, k=1)
        if hit:
            h = hit[0]
            return {"text": f"Vamos a [{stamp(h['start'])}], donde se habla de eso.",
                    "card": {"type": "moment", "t": round(h["start"], 2), "text": h["es"][:180]},
                    "action": {"type": "seek", "t": round(h["start"], 2)}}
    return None
