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
