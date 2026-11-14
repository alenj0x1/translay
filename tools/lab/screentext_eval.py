"""Evaluación del clasificador de texto en pantalla (vt/textkind.py) contra la referencia etiquetada.

  python tools/lab/screentext_eval.py                 puntaje, confusiones y errores
  python tools/lab/screentext_eval.py --save          además guarda el puntaje como la nueva línea base
  python tools/lab/screentext_eval.py --pending       renglones leídos en el laboratorio que aún no tienen etiqueta

Loop de mejora: el laboratorio (tools/lab/screentext.py) lee videos reales una vez; sus renglones se
etiquetan en tools/lab/screentext_gold.json (cada bloque con el tipo correcto de cada renglón y de
qué video salió); esta evaluación re-clasifica todo en menos de un segundo. Un cambio en las reglas
se queda solo si sube el puntaje sin bajar ningún tipo (lo compara con la línea base guardada).

Lo que importa para la persona: lo que se tradujo y no debía (código traducido arruina el video)
pesa más que lo que no se tradujo y debía. Por eso el puntaje principal es el de «se traduce o no»,
con los dos errores por separado.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vt import textkind  # noqa: E402

GOLD = Path(__file__).with_name("screentext_gold.json")
BASE = ROOT / "data" / "labs" / "screentext" / "baseline.json"
OUT = ROOT / "data" / "labs" / "screentext" / "out"


def load() -> list[dict]:
    return json.loads(GOLD.read_text(encoding="utf-8"))


def predict(lines: list[str], h: float | None = None, conf: float | None = None) -> list[str]:
    """h: alto de un renglón en fracción del cuadro; conf: confianza del OCR (para los tipos que dependen
    del lugar y de la lectura)."""
    ctx = {"h": h, **({"conf": conf} if conf is not None else {})} if h else None
    return textkind.settle([textkind.kind(t, ctx) for t in lines])


def evaluate(gold: list[dict]) -> dict:
    conf = Counter()
    errors = []
    bad_tr = miss_tr = n = ok = 0
    for g in gold:
        lines = g["lines"]
        exp = g["kinds"] if len(g["kinds"]) == len(lines) else g["kinds"] * len(lines)
        got = predict(lines, g.get("h"), g.get("conf"))
        for t, e, p in zip(lines, exp, got):
            n += 1
            conf[(e, p)] += 1
            if e == p:
                ok += 1
                continue
            te, tp = textkind.translatable(e), textkind.translatable(p)
            if tp and not te:
                bad_tr += 1
            elif te and not tp:
                miss_tr += 1
            errors.append({"src": g.get("src", ""), "text": t, "expected": e, "got": p, "block": len(lines) > 1})
    per = {}
    for k in {e for e, _ in conf}:
        tot = sum(v for (e, _), v in conf.items() if e == k)
        per[k] = round(conf[(k, k)] / tot, 3) if tot else None
    return {"lines": n, "accuracy": round(ok / n, 4) if n else 0, "translated_wrongly": bad_tr,
            "not_translated": miss_tr, "per_kind": dict(sorted(per.items())),
            "confusion": {f"{e}→{p}": v for (e, p), v in sorted(conf.items()) if e != p}, "errors": errors}


def pipeline(gold: list[dict], only: set | None = None) -> dict:
    """Lo que guardó el laboratorio (items.json, con el contexto del cuadro y la unión de renglones) contra
    la referencia, por texto exacto. Mide lo que el clasificador solo no ve; hay que volver a leer el video."""
    ref = {"\n".join(g["lines"]): g["kinds"][0] for g in gold if len(set(g["kinds"])) == 1}
    n = ok = bad = 0
    wrong = Counter()
    for f in sorted(OUT.glob("*/items.json")):
        if only and f.parent.name not in only:
            continue
        for it in json.loads(f.read_text(encoding="utf-8")):
            e = ref.get(it["text"])
            if e is None:
                continue
            n += 1
            if e == it["kind"]:
                ok += 1
            else:
                wrong[f"{e}→{it['kind']}"] += 1
                bad += textkind.translatable(it["kind"]) and not textkind.translatable(e)
    return {"items": n, "accuracy": round(ok / n, 4) if n else 0, "translated_wrongly": bad, "confusion": dict(wrong)}


def pending(gold: list[dict]) -> list[dict]:
    """Bloques leídos en el laboratorio que la referencia aún no tiene."""
    known = {"\n".join(g["lines"]) for g in gold}
    out = []
    for f in sorted(OUT.glob("*/items.json")):
        for it in json.loads(f.read_text(encoding="utf-8")):
            if it["text"] not in known:
                known.add(it["text"])
                h = round(it["box"][3] / max(1, it.get("lines") or 1), 4)
                out.append({"src": f.parent.name, "lines": it["text"].split("\n"), "h": h, "conf": it["conf"],
                            "got": predict(it["text"].split("\n"), h, it["conf"])})
    return out


def _num(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def add(path: Path, gold: list[dict]) -> int:
    """Etiquetas de un archivo de texto, una por línea: «tipo ¦ video ¦ texto». En un bloque, los
    renglones van separados por « ⏎ » y el tipo puede ser uno para todos o uno por renglón
    («comment,code,code»). Las líneas que empiezan con // son notas. Lo ya etiquetado no se repite."""
    known = {"\n".join(g["lines"]) for g in gold}
    n = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.startswith("//"):
            continue
        parts = [x.strip() for x in raw.split(" ¦ ", 3)]
        # «tipo ¦ video ¦ texto», o «tipo ¦ video ¦ alto@confianza ¦ texto» (alto del renglón en fracción del cuadro)
        kinds, src, where, text = (parts if len(parts) == 4 and _num(parts[2].split("@")[0])
                                   else (parts[0], parts[1], None, " ¦ ".join(parts[2:])))
        h, _, c = (where or "").partition("@")
        lines = text.split(" ⏎ ")
        if "\n".join(lines) in known:
            continue
        unknown = [k for k in kinds.split(",") if k not in textkind.KINDS]
        if unknown:
            raise SystemExit(f"tipo desconocido {unknown} en: {raw}")
        known.add("\n".join(lines))
        gold.append({"src": src, "lines": lines, "kinds": kinds.split(","), **({"h": float(h)} if h else {}),
                     **({"conf": float(c)} if c else {})})
        n += 1
    GOLD.write_text(json.dumps(gold, ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--save", action="store_true", help="guardar como línea base")
    ap.add_argument("--pending", action="store_true", help="listar lo que falta etiquetar")
    ap.add_argument("--add", type=Path, help="agregar etiquetas desde un archivo «tipo ¦ video ¦ texto»")
    ap.add_argument("--pipeline", nargs="*", help="medir lo guardado por el laboratorio (opcional: qué videos)")
    a = ap.parse_args()
    gold = load()
    if a.pipeline is not None:
        r = pipeline(gold, set(a.pipeline) or None)
        print(f"pipeline: {r['items']} elementos · acierto {r['accuracy']:.1%} · traducidos sin deber "
              f"{r['translated_wrongly']} · {r['confusion']}")
        return
    if a.add:
        print(f"+{add(a.add, gold)} bloques → {len(gold)} en la referencia")
    if a.pending:
        for p in pending(gold):
            print(json.dumps(p, ensure_ascii=False))
        return
    r = evaluate(gold)
    print(f"{r['lines']} renglones · acierto {r['accuracy']:.1%} · traducidos sin deber {r['translated_wrongly']} · "
          f"sin traducir debiendo {r['not_translated']}")
    print("por tipo:", r["per_kind"])
    if r["confusion"]:
        print("confusiones:", r["confusion"])
    for e in r["errors"]:
        print(f"  ✗ [{e['src']}] {e['expected']}→{e['got']}{' (bloque)' if e['block'] else ''}: {e['text']}")
    if BASE.exists():
        b = json.loads(BASE.read_text(encoding="utf-8"))
        worse = [k for k, v in r["per_kind"].items() if v is not None and b["per_kind"].get(k) not in (None,)
                 and v < b["per_kind"][k]]
        print(f"línea base: {b['accuracy']:.1%} ({b['lines']} renglones) → ahora {r['accuracy']:.1%}"
              + (f" · BAJÓ en {worse}" if worse else ""))
    if a.save:
        BASE.parent.mkdir(parents=True, exist_ok=True)
        BASE.write_text(json.dumps({k: v for k, v in r.items() if k != "errors"}, ensure_ascii=False, indent=1),
                        encoding="utf-8")


if __name__ == "__main__":
    main()
