"""Translation lab per language pair: which translator wins for each source language → Spanish.

Data: FLEURS (Google, CC-BY-4.0): the same sentences in each language with their text; the Spanish is
Latin American (es_419), so it works as the reference. Downloaded once to data/labs/languages/fleurs/
(tools/lab/langs_data.py).

Measures, per translator and pair:
  chrF        similarity to the reference translation (0-100; higher is better), corpus level
  chrF app    the same, with Translay's text processing around it (vt/textproc.py)
  ms/sent.    one sentence at a time, as when watching live
  sent./s     batches of 24, as when translating a whole video
  VRAM        MB the loaded model takes

It also writes typical video sentences (SENTENCES) translated side by side, to read.

    python tools/lab/langs_mt.py --pair pt-es --models opus-itc nllb-1.3b madlad-3b
    python tools/lab/langs_mt.py --pair en-es --models opus-big nllb-1.3b
"""

import argparse
import csv
import json
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from vt.translate import CT2Translator  # noqa: E402

DATA = ROOT / "data" / "labs" / "languages"
FLEURS = {"en": "en_us", "pt": "pt_br", "es": "es_419"}

# typical video sentences (tutorial, vlog, review, gaming), written for the lab
SENTENCES = {
    "pt": [
        "Fala, galera! Tudo bem com vocês? Bem-vindos de volta ao canal.",
        "Hoje eu vou mostrar pra vocês como configurar o servidor do zero.",
        "Primeiro, você abre o terminal e digita esse comando aqui.",
        "Se der algum erro, é só reiniciar e tentar de novo.",
        "Cara, eu não esperava isso de jeito nenhum.",
        "Esse celular custou os olhos da cara, mas valeu muito a pena.",
        "Não esquece de deixar o like e se inscrever no canal.",
        "A gente vai fazer uma pausa rápida e já volta.",
        "Ele pisou na bola feio nessa última partida.",
        "Pra ser sincero, a bateria dura o dia inteiro tranquilamente.",
        "Vocês podem ver que o resultado ficou bem melhor do que antes.",
        "Bora começar? Então, vamos lá.",
        "O que vocês acharam? Me contem aqui nos comentários.",
        "Isso aqui é moleza, qualquer um consegue fazer.",
        "Tá chovendo muito aqui em São Paulo hoje.",
        "Fica ligado que no próximo vídeo tem mais.",
    ],
    "en": [
        "Hey guys, what's up? Welcome back to the channel.",
        "Today I'm going to show you how to set up the server from scratch.",
        "If you run into any issues, just restart the server and try again.",
        "I'm gonna be honest with you, I wasn't expecting that at all.",
        "Don't forget to smash that like button and subscribe.",
    ],
}


def load_fleurs(src: str, tgt: str, split: str, n: int) -> list[tuple[str, str]]:
    """(source, reference) pairs with the same sentence id."""
    def read(lang):
        out = {}
        with open(DATA / "fleurs" / f"{FLEURS[lang]}.{split}.tsv", encoding="utf-8", newline="") as f:
            for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
                out.setdefault(row[0], row[2])  # several recordings per sentence, same text
        return out

    a, b = read(src), read(tgt)
    ids = sorted(set(a) & set(b), key=int)[:n]
    return [(a[i], b[i]) for i in ids]


def _ngrams(s: str, n: int) -> Counter:
    s = s.replace(" ", "")
    return Counter(s[i:i + n] for i in range(len(s) - n + 1))


def chrf(hyps: list[str], refs: list[str], order: int = 6, beta: float = 2.0) -> float:
    """Corpus-level chrF (like sacrebleu): character n-grams 1..6, F with beta=2."""
    match, hyp_tot, ref_tot = [0] * order, [0] * order, [0] * order
    for h, r in zip(hyps, refs):
        for n in range(1, order + 1):
            hc, rc = _ngrams(h, n), _ngrams(r, n)
            match[n - 1] += sum((hc & rc).values())
            hyp_tot[n - 1] += sum(hc.values())
            ref_tot[n - 1] += sum(rc.values())
    p = statistics.mean(m / t if t else 0 for m, t in zip(match, hyp_tot))
    r = statistics.mean(m / t if t else 0 for m, t in zip(match, ref_tot))
    return 100 * (1 + beta ** 2) * p * r / (beta ** 2 * p + r) if p + r else 0.0


def vram_mb() -> int:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout
    return int(out.split()[0]) if out.strip() else 0


def run(model: str, src: str, tgt: str, pairs, sentences, device: str) -> dict:
    base = vram_mb()
    t = time.perf_counter()
    tr = CT2Translator(model, device=device, src=src, tgt=tgt)
    load_s = time.perf_counter() - t
    tr.translate_batch(["warm up"])
    srcs, refs = [p[0] for p in pairs], [p[1] for p in pairs]

    t = time.perf_counter()
    hyps = []
    for k in range(0, len(srcs), 24):
        hyps += tr.translate_batch(srcs[k:k + 24])
    batch_s = time.perf_counter() - t
    mem = vram_mb() - base

    lat = []
    for s in srcs[:40]:
        t = time.perf_counter()
        tr.translate_batch([s])
        lat.append((time.perf_counter() - t) * 1000)

    # as in Translay: split sentences, the language's text rules (vt/textproc.py) and Latin American polish
    piped = tr.translate_many(srcs)
    video = tr.translate_many(sentences) if sentences else []
    del tr
    return {"model": Path(model).name, "chrf": round(chrf(hyps, refs), 2), "chrf_app": round(chrf(piped, refs), 2),
            "ms": round(statistics.median(lat), 1), "per_s": round(len(srcs) / batch_s, 1), "vram_mb": mem,
            "load_s": round(load_s, 1), "hyps": hyps, "video": video}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pair", default="pt-es", help="source-target, e.g. pt-es")
    ap.add_argument("--models", nargs="+", required=True, help="names from vt/translate.py or CTranslate2 folders")
    ap.add_argument("--split", default="test", choices=["test", "dev"])
    ap.add_argument("-n", type=int, default=400, help="FLEURS sentences")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--out", default=str(DATA / "mt"))
    a = ap.parse_args()

    src, tgt = a.pair.split("-")
    pairs = load_fleurs(src, tgt, a.split, a.n)
    sentences = SENTENCES.get(src, [])
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f"{a.pair}: {len(pairs)} FLEURS sentences ({a.split})", flush=True)

    results = []
    for m in a.models:
        r = run(m, src, tgt, pairs, sentences, a.device)
        print(f"  {r['model']:<26} chrF {r['chrf']:>6} (app {r['chrf_app']:>6})  {r['ms']:>6} ms/sent.  "
              f"{r['per_s']:>6} sent./s  {r['vram_mb']:>5} MB  load {r['load_s']} s", flush=True)
        results.append(r)

    (out / f"{a.pair}.json").write_text(json.dumps(
        {"pair": a.pair, "split": a.split, "n": len(pairs), "src": [p[0] for p in pairs],
         "ref": [p[1] for p in pairs], "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")

    md = [f"# {a.pair} · FLEURS {a.split} · {len(pairs)} sentences\n",
          "| Translator | chrF | chrF app | ms/sent. | sent./s | VRAM MB | load s |", "|---|---|---|---|---|---|---|"]
    md += [f"| {r['model']} | {r['chrf']} | {r['chrf_app']} | {r['ms']} | {r['per_s']} | {r['vram_mb']} | {r['load_s']} |"
           for r in results]
    if sentences:
        md.append("\n## Video sentences\n")
        for i, s in enumerate(sentences):
            md.append(f"**{s}**\n")
            md += [f"- {r['model']}: {r['video'][i]}" for r in results]
            md.append("")
    (out / f"{a.pair}.md").write_text("\n".join(md), encoding="utf-8")
    print(f"→ {out / (a.pair + '.md')}")


if __name__ == "__main__":
    main()
