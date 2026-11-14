"""Todo lo que se sabe de un video, para un agente: lo que se dice y lo que se ve.

  elements(screen)        lo escrito en el video que conviene tener a mano: código, comandos, enlaces,
                          correos, cuentas y comentarios del código, sin repetidos, con su minuto
  markdown(...)           un documento para pegar en un agente (o dárselo al de Translay): datos del video,
                          hasta dónde lo vio la persona, resumen, transcripción con hora y persona,
                          traducción, elementos de la pantalla y comentarios

Las horas van como [m:ss] (o [h:mm:ss]) para que el agente pueda citar el momento exacto.
"""

from __future__ import annotations

ELEMENT_KINDS = ("code", "command", "link", "email", "handle", "comment")
# textos del documento en cada idioma: «en» para los modelos (entienden mejor las instrucciones en inglés y
# responden en el idioma que se les pide); «es» y «pt» para quien lo copia o lo pide por la API
TEXT = {
    "en": {"code": "Code", "command": "Command", "link": "Link", "email": "Email", "handle": "Account",
           "comment": "Code comment", "channel": "Channel", "url": "Link", "duration": "Duration", "lang": "Language",
           "watched": "The person watched up to {at} ({pct} %)",
           "cite": "Times in square brackets are moments in the video: cite them when answering.",
           "summary": "Summary", "transcript": "Transcript",
           "bilingual": "Each sentence in its original language and, below it, its translation into {lang}.",
           "note": "Person's note", "screen": "On screen",
           "screen_intro": "What is written in the video (code, commands, links…), with the moment it appears."},
    "es": {"code": "Código", "command": "Comando", "link": "Enlace", "email": "Correo", "handle": "Cuenta",
           "comment": "Comentario del código", "channel": "Canal", "url": "Enlace", "duration": "Duración",
           "lang": "Idioma", "watched": "La persona lo vio hasta {at} ({pct} %)",
           "cite": "Las horas entre corchetes son el momento del video: cítalas al responder.",
           "summary": "Resumen", "transcript": "Transcripción",
           "bilingual": "Cada frase en su idioma original y, debajo, su traducción al {lang}.",
           "note": "Nota de la persona", "screen": "En pantalla",
           "screen_intro": "Lo que está escrito en el video (código, comandos, enlaces…), con el momento en que aparece."},
    "pt": {"code": "Código", "command": "Comando", "link": "Link", "email": "E-mail", "handle": "Conta",
           "comment": "Comentário do código", "channel": "Canal", "url": "Link", "duration": "Duração",
           "lang": "Idioma", "watched": "A pessoa assistiu até {at} ({pct} %)",
           "cite": "Os horários entre colchetes são momentos do vídeo: cite-os ao responder.",
           "summary": "Resumo", "transcript": "Transcrição",
           "bilingual": "Cada frase no idioma original e, abaixo, a tradução para o {lang}.",
           "note": "Nota da pessoa", "screen": "Na tela",
           "screen_intro": "O que está escrito no vídeo (código, comandos, links…), com o momento em que aparece."},
}
LABEL = TEXT["es"]  # compatibilidad


def stamp(t: float) -> str:
    t = int(max(0, t or 0))
    return f"{t // 3600}:{t // 60 % 60:02}:{t % 60:02}" if t >= 3600 else f"{t // 60}:{t % 60:02}"


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


def elements(screen: dict | None) -> list[dict]:
    """Elementos del texto en pantalla (vt/screentext.py): uno por texto distinto, con la primera vez que
    aparece y cuántas veces volvió. Un bloque que es el comienzo de otro más completo (se escribía en vivo)
    queda solo en su versión completa."""
    items = [it for it in (screen or {}).get("items", []) if it.get("kind") in ELEMENT_KINDS]
    items.sort(key=lambda it: it["start"])
    out: list[dict] = []
    by_text: dict[str, dict] = {}
    for it in items:
        key = _norm(it["text"])
        if len(key) < 3:
            continue
        if key in by_text:
            e = by_text[key]
            e["times"].append(round(it["start"], 2))
            e["end"] = max(e["end"], it["end"])
            continue
        # se escribía en vivo: el anterior era el comienzo de este
        prev = next((e for e in reversed(out[-6:]) if e["kind"] == it["kind"] and key.startswith(_norm(e["text"]))
                     and it["start"] - e["end"] < 30), None)
        if prev:
            del by_text[_norm(prev["text"])]
            prev.update(text=it["text"], end=it["end"])
            by_text[key] = prev
            continue
        e = {"id": it["id"], "kind": it["kind"], "text": it["text"], "start": round(it["start"], 2),
             "end": it["end"], "times": [round(it["start"], 2)], "translation": it.get("translation")}
        out.append(e)
        by_text[key] = e
    return out


def markdown(info: dict, tr, screen: dict | None = None, position: float | None = None,
             with_translation: bool = True, ui: str = "en") -> str:
    """info: los datos de la biblioteca (title, url, channel, duration). tr: la transcripción (vt/store.py).
    ui: idioma de los textos del documento («en» para los modelos)."""
    from . import langs

    L = TEXT.get(ui, TEXT["en"])
    title = info.get("title") or tr.data.get("name") or tr.data["id"]
    dur = float(info.get("duration") or 0)
    out = [f"# {title}", ""]
    meta = []
    if info.get("channel"):
        meta.append(f"{L['channel']}: {info['channel']}")
    if info.get("url"):
        meta.append(f"{L['url']}: {info['url']}")
    if dur:
        meta.append(f"{L['duration']}: {stamp(dur)}")
    if tr.lang:
        meta.append(f"{L['lang']}: {tr.lang}")
    if position is not None and dur:
        meta.append(L["watched"].format(at=f"[{stamp(position)}]", pct=min(100, round(100 * position / dur))))
    out += [f"- {m}" for m in meta] + [""]
    out.append(L["cite"])
    out.append("")

    summary = tr.data.get("summary")
    if summary:
        out += [f"## {L['summary']}", "", summary.get("overview", "").strip(), ""]
        out += [f"- [{stamp(p.get('t', 0))}] {p.get('text', '').strip()}" for p in summary.get("points", [])]
        out.append("")

    names = tr.data.get("speaker_names") or {}
    order: dict = {}
    for s in tr.segments:
        if s.get("speaker") is not None and s["speaker"] not in order:
            order[s["speaker"]] = len(order) + 1
    translated = with_translation and tr.translates
    out += [f"## {L['transcript']}", ""]
    if translated:
        out += [L["bilingual"].format(lang=langs.name(tr.target, ui)), ""]
    comments = tr.data.get("comments") or {}
    for s in sorted(tr.segments, key=lambda x: x["start"]):
        who = ""
        if len(order) > 1 and s.get("speaker") is not None:
            who = " " + (names.get(str(s["speaker"])) or f"P{order[s['speaker']]}") + ":"
        out.append(f"[{stamp(s['start'])}]{who} {s.get('text', '').strip()}")
        if translated and s.get("translation"):
            out.append(f"  → {s['translation'].strip()}")
        for c in comments.get(str(s["id"]), []):
            out.append(f"  » {L['note']}: {c['text']}")
    out.append("")

    els = elements(screen)
    if els:
        out += [f"## {L['screen']}", "", L["screen_intro"], ""]
        for e in els:
            when = ", ".join(f"[{stamp(t)}]" for t in e["times"][:4]) + (" …" if len(e["times"]) > 4 else "")
            if e["kind"] in ("code", "command"):
                out += [f"{L[e['kind']]} {when}:", "```", e["text"], "```"]
            else:
                tail = f" → {e['translation']}" if e.get("translation") else ""
                out.append(f"- {L[e['kind']]} {when}: {e['text']}{tail}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"
