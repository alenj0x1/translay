"""Pruebas sin GPU de la detección de hardware (vt/hardware.py).

    python -m pytest tests/test_hardware.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vt import hardware  # noqa: E402

FAKE_GPU = {"index": 0, "name": "NVIDIA GeForce RTX 4060", "vram_total_mb": 8188, "vram_used_mb": 1000,
            "vram_free_mb": 7188, "driver": "610.88", "compute_cap": "8.9", "util": 3}


def test_detect_shape(monkeypatch):
    monkeypatch.delenv("TRANSLAY_EMULATE", raising=False)
    monkeypatch.setattr(hardware, "gpus", lambda max_age=5.0: [FAKE_GPU])
    d = hardware.detect()
    assert d["gpu"]["name"] == "NVIDIA GeForce RTX 4060" and d["gpu"]["cuda"] is True
    assert d["ram"]["total_mb"] and d["ram"]["total_mb"] > 0
    assert d["cpu"]["threads"] >= 1 and 1 <= d["cpu"]["usable_threads"] <= d["cpu"]["threads"]
    assert d["emulated"] is None


def test_no_gpu(monkeypatch):
    monkeypatch.delenv("TRANSLAY_EMULATE", raising=False)
    monkeypatch.setattr(hardware, "gpus", lambda max_age=5.0: [])
    assert hardware.detect()["gpu"] is None


def test_emulated_lab(monkeypatch):
    monkeypatch.setattr(hardware, "gpus", lambda max_age=5.0: [FAKE_GPU])
    monkeypatch.setenv("TRANSLAY_EMULATE", json.dumps({"vram_mb": 4096, "ram_mb": 8192, "threads": 4}))
    d = hardware.detect()
    assert d["gpu"]["vram_total_mb"] == 4096
    assert d["ram"]["total_mb"] == 8192 and d["ram"]["limit_mb"] == 8192
    assert d["cpu"]["usable_threads"] == 4


def test_emulated_without_gpu(monkeypatch):
    monkeypatch.setattr(hardware, "gpus", lambda max_age=5.0: [FAKE_GPU])
    monkeypatch.setenv("TRANSLAY_EMULATE", json.dumps({"gpu": False}))
    assert hardware.detect()["gpu"] is None


def test_nvidia_smi_parsing(monkeypatch):
    class Out:
        stdout = "NVIDIA GeForce GTX 1650, 4096, 512, 3584, 552.22, 7.5, 0\n"

    monkeypatch.setattr(hardware.shutil, "which", lambda n: "nvidia-smi")
    monkeypatch.setattr(hardware.subprocess, "run", lambda *a, **k: Out())
    g = hardware._nvidia_smi()
    assert g == [{"index": 0, "name": "NVIDIA GeForce GTX 1650", "vram_total_mb": 4096, "vram_used_mb": 512,
                  "vram_free_mb": 3584, "driver": "552.22", "compute_cap": "7.5", "util": 0}]


# ------------------------------------------------------------------ memoria unificada (DGX Spark / GB10)
SPARK_GPU = {"index": 0, "name": "NVIDIA GB10", "vram_total_mb": None, "vram_used_mb": None,
             "vram_free_mb": None, "driver": "580.173.02", "compute_cap": "12.1", "util": 0}


def _spark(monkeypatch, mode="ATS"):
    monkeypatch.delenv("TRANSLAY_EMULATE", raising=False)
    monkeypatch.delenv("TRANSLAY_UNIFIED_MEMORY", raising=False)
    monkeypatch.setattr(hardware, "gpus", lambda max_age=5.0: [SPARK_GPU])
    monkeypatch.setattr(hardware, "_addressing_mode", lambda index: mode)
    monkeypatch.setattr(hardware, "ram", lambda: {"total_mb": 124546, "available_mb": 100000, "limit_mb": None})


def test_unified_memory_uses_system_ram(monkeypatch):
    _spark(monkeypatch)
    g = hardware.detect()["gpu"]
    assert g["unified"] is True
    assert g["vram_total_mb"] == 124546 and g["vram_free_mb"] == 100000 and g["vram_used_mb"] == 24546


def test_unified_memory_respects_container_limit(monkeypatch):
    _spark(monkeypatch)
    monkeypatch.setattr(hardware, "ram", lambda: {"total_mb": 124546, "available_mb": 100000, "limit_mb": 32768})
    g = hardware.detect()["gpu"]
    assert g["vram_total_mb"] == 32768 and g["vram_free_mb"] == 32768


def test_discrete_gpus_unchanged(monkeypatch):
    """Una GPU con VRAM propia no se toca, aunque el driver diga ATS (p. ej. GH200)."""
    monkeypatch.delenv("TRANSLAY_EMULATE", raising=False)
    monkeypatch.delenv("TRANSLAY_UNIFIED_MEMORY", raising=False)
    monkeypatch.setattr(hardware, "gpus", lambda max_age=5.0: [FAKE_GPU])
    monkeypatch.setattr(hardware, "_addressing_mode", lambda index: "ATS")
    g = hardware.detect()["gpu"]
    assert "unified" not in g and g["vram_total_mb"] == 8188


def test_unknown_memory_without_ats_stays_unknown(monkeypatch):
    _spark(monkeypatch, mode="None")
    g = hardware.detect()["gpu"]
    assert "unified" not in g and g["vram_total_mb"] is None


def test_unified_memory_override(monkeypatch):
    _spark(monkeypatch, mode="None")
    monkeypatch.setenv("TRANSLAY_UNIFIED_MEMORY", "1")
    assert hardware.detect()["gpu"]["unified"] is True
    _spark(monkeypatch)
    monkeypatch.setenv("TRANSLAY_UNIFIED_MEMORY", "0")
    assert "unified" not in hardware.detect()["gpu"]


def test_unified_memory_profiles(monkeypatch):
    """Con la memoria detectada, la GB10 deja de verse «sin GPU» y el automático elige la máxima calidad."""
    from vt import profiles

    _spark(monkeypatch)
    hw = hardware.detect()
    assert profiles.effective(hw)["gpu"] is True
    assert profiles.recommend(hw) == "calidad"
    calidad = next(r for r in profiles.evaluate(hw) if r["id"] == "calidad")
    assert calidad["state"] == "bien" and not calidad["notes"]


def test_addressing_mode_query_failure(monkeypatch):
    """Un driver que no conoce el campo (o falla) no rompe nada: no es memoria unificada."""
    class Out:
        returncode = 6
        stdout = "Field \"addressing_mode\" is not a valid field to query.\n"

    hardware._modes.clear()
    monkeypatch.delenv("TRANSLAY_UNIFIED_MEMORY", raising=False)
    monkeypatch.setattr(hardware.shutil, "which", lambda n: "nvidia-smi")
    monkeypatch.setattr(hardware.subprocess, "run", lambda *a, **k: Out())
    assert hardware._addressing_mode(0) is None
    assert hardware.unified_memory(SPARK_GPU) is False
    hardware._modes.clear()
