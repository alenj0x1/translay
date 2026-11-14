"""Laboratorio de adherencia al idioma: ¿los modelos del agente responden en el idioma de la app?

Los prompts (vt/agent.py, vt/digest.py, vt/agent.describe_messages) están en inglés y piden escribir en el
idioma elegido (es, en o pt). Aquí se mide, por modelo e idioma, qué parte de las salidas sale en ese idioma:

  respuestas   preguntas de tools/lab/agent_questions.json (escritas en español: para en y pt es el caso más
               difícil, la pregunta en otro idioma) sobre videos en inglés con su traducción al español
  descripción  la descripción corta de cada video
  resumen      una parte del resumen (capítulos y términos, JSON) y su cierre

    python tools/lab/lang_adherence.py                              los modelos por defecto de cada equipo
    python tools/lab/lang_adherence.py --models qwen3.5-0.8b --langs pt
    python tools/lab/lang_adherence.py --report

El idioma de cada salida se decide por palabras frecuentes exclusivas de cada idioma (detect()). Resultados en
data/labs/languages/adherence/<modelo>.jsonl y la tabla en adherence.md.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vt import agent, digest, langs, llm  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from agent import QUESTIONS, VIDEOS, load_video  # noqa: E402

OUT = ROOT / "data" / "labs" / "languages" / "adherence"
LAB = ROOT / "data" / "labs" / "agent"
# los que elige la app según el equipo (vt/agentsvc.py) y el de la descripción corta
DEFAULT_MODELS = ["qwen3.5-4b", "gemma4-e2b", "qwen3.5-2b", "qwen3.5-0.8b"]

# palabras frecuentes que casi no aparecen en los otros dos idiomas
MARKERS = {
    "es": set("el los del las y pero muy esto eso hay también cómo qué cuando donde puede porque sobre "
              "una unos este esta están según usted ustedes hace explica".split()),
    "pt": set("o os do da dos das em um uma não você vocês é ao à isso isto mais também então muito pelo pela "
              "são está como quando onde pode porque sobre seu sua explica nos nas".split()),
    "en": set("the of and to in is you that it was for on are with this have from or by but not what all "
              "were when your can which their if will about how explains uses video".split()),
}
# compartidas entre español y portugués: no deciden entre ellos
for _w in ("como", "quando", "onde", "pode", "porque", "sobre", "explica", "também", "está"):
    MARKERS["es"].discard(_w)
    MARKERS["pt"].discard(_w)


def detect(text: str) -> str:
    """'es', 'en' o 'pt' (o '' si no hay texto). Sin bloques de código ni marcas de tiempo."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\[\d+:\d{2}(:\d{2})?\]", " ", text)
    words = re.findall(r"[a-záéíóúâêôãõçàñü]+", text.lower())
    if not words:
        return ""
    score = {k: sum(w in m for w in words) for k, m in MARKERS.items()}
    return max(score, key=score.get) if max(score.values()) else ""


def json_text(raw: str) -> str:
    """El texto legible de una salida JSON del resumen (títulos, puntos, explicaciones)."""
    d = digest._json(raw)
    parts = []

    def walk(x):
        if isinstance(x, str):
            if not re.fullmatch(r"\d+:\d{2}(:\d{2})?", x.strip()):
                parts.append(x)
        elif isinstance(x, dict):
            for k, v in x.items():
                if k not in ("t", "term"):
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(d)
    return " ".join(parts)


def run(models: list[str], ui_langs: list[str], n_questions: int, build: str, device: str | None):
    exe = llm.ensure(build, LAB)
    qs = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    vids = sorted({q["video"] for q in qs if (VIDEOS / f"{q['video']}.json").exists()})
    per_video = max(1, n_questions // len(vids))
    picked = [q for v in vids for q in [q for q in qs if q["video"] == v and not q.get("trap")][:per_video]]
    OUT.mkdir(parents=True, exist_ok=True)
    for key in models:
        path = llm.model_file(key)
        srv = llm.Server(exe, path, ctx=16384, gpu_layers=99, device=device, log=OUT / f"{key}.log")
        srv.start()
        out = (OUT / f"{key}.jsonl").open("a", encoding="utf-8")
        print(f"== {llm.MODELS[key].name}: cargó en {srv.load_s:.1f} s", flush=True)
        try:
            for lang in ui_langs:
                rows = []

                def record(task, text, extra=None):
                    got = detect(text)
                    row = {"model": key, "lang": lang, "task": task, "got": got, "ok": got == lang,
                           "text": text[:600], "time": time.time(), **(extra or {})}
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
                    out.flush()
                    rows.append(row)

                for q in picked:
                    info, tr, screen = load_video(q["video"])
                    msgs, _ = agent.messages(info, tr, screen, q["q"], position=q.get("position"), budget=10000, lang=lang)
                    r = srv.chat(msgs, max_tokens=260, temperature=0.2, chat_template_kwargs={"enable_thinking": False})
                    record("respuesta", agent.clean(r["text"]), {"video": q["video"], "q": q["q"]})
                for v in vids:
                    info, tr, screen = load_video(v)
                    r = srv.chat(agent.describe_messages(info, tr, lang=lang), max_tokens=160, temperature=0.3,
                                 chat_template_kwargs={"enable_thinking": False})
                    record("descripción", agent.clean_description(r["text"]), {"video": v})
                for v in vids[:2]:
                    info, tr, screen = load_video(v)
                    lines = digest._lines(tr, screen)
                    chunk = digest._chunks(lines, 9000)[0]
                    language = langs.PROMPT[lang]
                    user = f"Video: {info['title']}\nPart 1 of 1\n\n" + "\n".join(s for _, s in chunk)
                    r = srv.chat([{"role": "system", "content": digest.SECTION_SYSTEM.format(language=language)},
                                  {"role": "user", "content": user}], max_tokens=1600, temperature=0.2,
                                 chat_template_kwargs={"enable_thinking": False},
                                 response_format={"type": "json_schema", "json_schema": {"schema": digest.SECTION_SCHEMA}})
                    record("resumen", json_text(r["text"]), {"video": v})
                    outline = json_text(r["text"])[:3000]
                    r = srv.chat([{"role": "system", "content": digest.FINAL_SYSTEM.format(language=language)},
                                  {"role": "user", "content": f"Video: {info['title']}\n\n{outline}"}], max_tokens=900,
                                 temperature=0.3, chat_template_kwargs={"enable_thinking": False},
                                 response_format={"type": "json_schema", "json_schema": {"schema": digest.FINAL_SCHEMA}})
                    record("cierre", json_text(r["text"]), {"video": v})
                ok = sum(r["ok"] for r in rows)
                bad = [f"{r['task']}→{r['got'] or '?'}" for r in rows if not r["ok"]]
                print(f"  {lang}: {ok}/{len(rows)} en el idioma pedido" + (f" · fallas: {', '.join(bad)}" if bad else ""),
                      flush=True)
        finally:
            srv.stop()
            out.close()


def report():
    rows = []
    for f in sorted(OUT.glob("*.jsonl")):
        rows += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    tasks = ["respuesta", "descripción", "resumen", "cierre"]
    md = ["# Adherencia al idioma pedido", "",
          "| Modelo | Idioma | " + " | ".join(tasks) + " | Total |", "|---|---|" + "---|" * (len(tasks) + 1)]
    by = {}
    for r in rows:
        by.setdefault((r["model"], r["lang"]), []).append(r)
    for (m, lang), rs in sorted(by.items()):
        cells = []
        for t in tasks:
            x = [r for r in rs if r["task"] == t]
            cells.append(f"{sum(r['ok'] for r in x)}/{len(x)}" if x else "–")
        md.append(f"| {m} | {lang} | " + " | ".join(cells) + f" | {100 * sum(r['ok'] for r in rs) / len(rs):.0f} % |")
    (OUT / "adherence.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    ap.add_argument("--langs", nargs="+", default=list(langs.TARGETS))
    ap.add_argument("-n", type=int, default=10, help="preguntas por idioma (repartidas entre los videos)")
    ap.add_argument("--build", default="vulkan")
    ap.add_argument("--device", default="Vulkan0")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if not a.report:
        run(a.models, a.langs, a.n, a.build, a.device)
    report()


if __name__ == "__main__":
    main()
