"""Perfiles de rendimiento: qué modelos y parámetros usa Translay según el equipo.

Los números salen de los labs (tools/lab, data/labs/matriz-2-ruido): el mismo pipeline
de la cola, con límites reales de VRAM, RAM y CPU, en GPUs de 8, 6, 4 y 2 GB y sin GPU.
«speed» es cuántos segundos de video se procesan por segundo de reloj: con más de 1×
se puede ver en vivo (con la voz sincronizada, si el perfil tiene voz).

  recommend(hw, limits)        el mejor perfil que va bien en ese equipo
  evaluate(hw, limits)         cada perfil con su estado, velocidad, espera y tiempos
  effective(hw, limits)        el equipo que queda con los límites que puso la persona
"""

PROFILES = {
    "calidad": {
        "name": "Máxima calidad", "voice": True,
        "desc": "Reconocimiento grande en fp16 y voz clonada con 16 pasos.",
        "asr": "large-v3-turbo", "asr_ct": "float16", "beam": 5, "mt": "opus-big", "mt_ct": None, "steps": 16,
    },
    "equilibrado": {
        "name": "Equilibrado", "voice": True,
        "desc": "El mismo reconocimiento en int8 y voz clonada con 8 pasos: la mitad de memoria y de tiempo.",
        "asr": "large-v3-turbo", "asr_ct": "int8_float16", "beam": 5, "mt": "opus-big", "mt_ct": "int8_float16",
        "steps": 8,
    },
    "ligero": {
        "name": "Ligero", "voice": True,
        "desc": "Reconocimiento small y traductor base, con voz clonada de 8 pasos. Algo menos preciso con ruido.",
        "asr": "small", "asr_ct": "int8_float16", "beam": 3, "mt": "opus-base", "mt_ct": "int8", "steps": 8,
    },
    "texto": {
        "name": "Solo subtítulos", "voice": False,
        "desc": "Reconocimiento grande y traducción, sin voz en español.",
        "asr": "large-v3-turbo", "asr_ct": "int8_float16", "beam": 5, "mt": "opus-big", "mt_ct": "int8_float16",
        "steps": 0,
    },
    "texto-ligero": {
        "name": "Subtítulos ligeros", "voice": False,
        "desc": "Reconocimiento small y traductor base, sin voz. Funciona hasta sin GPU.",
        "asr": "small", "asr_ct": "int8", "beam": 3, "mt": "opus-base", "mt_ct": "int8", "steps": 0,
    },
}
ORDER = list(PROFILES)  # de más a menos exigente

# velocidad medida (× tiempo real) por VRAM de la tarjeta (GB); 0 = sin GPU (8 hilos)
SPEED = {
    "calidad":      {8: 2.19, 6: 0.94, 4: 0.54, 2: 0.25, 0: 0.02},
    "equilibrado":  {8: 2.69, 6: 2.45, 4: 0.89, 2: 0.46, 0: 0.03},
    "ligero":       {8: 2.45, 6: 2.33, 4: 1.30, 2: 0.47, 0: 0.04},
    "texto":        {8: 7.33, 6: 7.16, 4: 7.19, 2: 3.42, 0: 0.34},
    "texto-ligero": {8: 6.73, 6: 6.17, 4: 6.13, 2: 5.17, 0: 1.16},
}
# espera antes de reproducir para que la voz no se atrase (s), con la velocidad de arriba
WAIT = {
    "calidad":      {8: 4.3, 6: 24.4, 4: 67.4, 2: 211.6},
    "equilibrado":  {8: 3.5, 6: 2.3, 4: 16.8, 2: 83.6},
    "ligero":       {8: 2.0, 6: 3.7, 4: 2.2, 2: 79.9},
    "texto":        {8: 0.7, 6: 0.7, 4: 0.7, 2: 0.9},
    "texto-ligero": {8: 0.7, 6: 0.7, 4: 0.8, 2: 0.9},
}
# memoria medida: pico de VRAM de Translay (MB) y RAM comprometida (MB)
VRAM_MB = {"calidad": 4600, "equilibrado": 3500, "ligero": 3300, "texto": 1950, "texto-ligero": 650}
RAM_MB = {"calidad": 12200, "equilibrado": 10950, "ligero": 10700, "texto": 3550, "texto-ligero": 2250}
RAM_CPU_MB = {"texto": 4980, "texto-ligero": 3780}
LOAD_S = {"calidad": 25, "equilibrado": 20, "ligero": 17, "texto": 6, "texto-ligero": 3}

STATES = {
    "bien": "Va bien",
    "limite": "Al límite",
    "forzado": "Forzado",
    "muy-forzado": "Muy forzado",
}


def effective(hw: dict, limits: dict | None = None) -> dict:
    """VRAM (MB), RAM (MB) e hilos que Translay puede usar: el equipo, recortado por los límites."""
    limits = limits or {}
    g = hw.get("gpu")
    vram = (g.get("vram_total_mb") or 0) if g else 0  # «[N/A]» en algunas GPUs: como sin VRAM conocida
    if limits.get("vram_mb"):
        vram = min(vram, limits["vram_mb"]) if vram else 0
    r = hw.get("ram") or {}
    ram = r.get("limit_mb") or r.get("total_mb") or 0
    if limits.get("ram_mb"):
        ram = min(ram, limits["ram_mb"]) if ram else limits["ram_mb"]
    c = hw.get("cpu") or {}
    threads = c.get("usable_threads") or c.get("threads") or 1
    if limits.get("threads"):
        threads = min(threads, limits["threads"])
    return {"gpu": bool(g) and vram > 0, "vram_mb": vram, "ram_mb": ram, "threads": threads}


def _interp(table: dict, gb: float) -> float:
    """Valor medido para una VRAM dada (interpola entre los labs; más de 8 GB = como 8)."""
    pts = sorted((k, v) for k, v in table.items() if k > 0)
    if gb >= pts[-1][0]:
        return pts[-1][1]
    if gb <= pts[0][0]:
        return pts[0][1] * max(0.2, gb / pts[0][0])  # menos de 2 GB: peor aún
    for (a, va), (b, vb) in zip(pts, pts[1:]):
        if a <= gb <= b:
            return va + (vb - va) * (gb - a) / (b - a)
    return pts[-1][1]


def estimate(profile: str, eff: dict) -> dict:
    """Velocidad, espera para ver en vivo y estado de un perfil en ese equipo."""
    p = PROFILES[profile]
    notes = []
    if eff["gpu"]:
        gb = eff["vram_mb"] / 1024
        speed = _interp(SPEED[profile], gb)
        wait = _interp(WAIT[profile], gb) if speed >= 1 else None
        if gb < VRAM_MB[profile] / 1024 + 1.0:  # + ~1 GB del escritorio
            notes.append("No entra entero en la VRAM: el driver desborda a la memoria compartida y algunas frases tardan mucho más.")
    else:
        # sin GPU: medido con 8 hilos; con menos, proporcionalmente más lento (4 hilos ≈ 0.85×)
        speed = SPEED[profile][0] * min(1.0, 0.7 + 0.3 * eff["threads"] / 8)
        wait = 8.0 if speed >= 1 else None
        if p["voice"]:
            notes.append("Sin GPU, la voz clonada tarda decenas de minutos por cada minuto de video.")
    ram_need = (RAM_CPU_MB.get(profile) if not eff["gpu"] else None) or RAM_MB[profile]
    # los labs de 4 y 2 GB ya corrieron con 8 GB de RAM (la voz compromete ~11 GB y anduvo):
    # se penaliza solo con bastante menos RAM que eso
    ram_short = bool(eff["ram_mb"]) and ram_need > eff["ram_mb"] * 1.6
    if ram_short:
        notes.append(f"Necesita ~{round(ram_need / 1024)} GB de RAM y Translay tiene {round(eff['ram_mb'] / 1024)} GB: "
                     "Windows usará el disco y todo irá más lento.")
        speed *= 0.8
    state = "bien" if speed >= 1.5 else "limite" if speed >= 1.0 else "forzado" if speed >= 0.5 else "muy-forzado"
    if ram_short and state == "bien":
        state = "limite"
    return {"id": profile, "name": p["name"], "desc": p["desc"], "voice": p["voice"], "speed": round(speed, 2),
            "live": speed >= 1.0, "wait_s": round(wait, 1) if wait is not None else None,
            "state": state, "state_label": STATES[state], "notes": notes,
            "minutes_per_10": round(10 / speed + LOAD_S[profile] / 60, 1) if speed else None,
            "vram_mb": VRAM_MB[profile] if eff["gpu"] else 0, "ram_mb": ram_need}


def evaluate(hw: dict, limits: dict | None = None) -> list[dict]:
    eff = effective(hw, limits)
    return [estimate(k, eff) for k in ORDER]


def recommend(hw: dict, limits: dict | None = None) -> str:
    """El perfil más completo que se puede ver en vivo (va bien o al límite); si ninguno, subtítulos ligeros."""
    for r in evaluate(hw, limits):
        if r["state"] in ("bien", "limite"):
            return r["id"]
    return "texto-ligero"


def resolve(choice: str, hw: dict, limits: dict | None = None) -> str:
    """El perfil que se usa: el elegido, o el recomendado si es «auto»."""
    return choice if choice in PROFILES else recommend(hw, limits)
