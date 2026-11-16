"""El llama-server del agente fuera de Windows: el instalado (TRANSLAY_LLAMA_SERVER o el del PATH) en vez
de los zips oficiales, que son solo para Windows (la imagen de Docker trae uno compilado con CUDA)."""

import sys

import pytest

from vt import llm


def test_variable_gana(monkeypatch, tmp_path):
    exe = tmp_path / "llama-server"
    monkeypatch.setenv("TRANSLAY_LLAMA_SERVER", str(exe))
    assert llm.installed() == exe
    assert llm.ensure("vulkan", tmp_path) == exe  # no baja nada, sea cual sea el build
    assert llm.ensure("cpu", tmp_path) == exe
    assert not (tmp_path / "runtime").exists()


def test_path_fuera_de_windows(monkeypatch, tmp_path):
    monkeypatch.delenv("TRANSLAY_LLAMA_SERVER", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(llm.shutil, "which", lambda name: "/usr/local/bin/llama-server" if name == "llama-server" else None)
    assert str(llm.installed()) == "/usr/local/bin/llama-server"


def test_sin_binario_fuera_de_windows_no_baja_el_de_windows(monkeypatch, tmp_path):
    monkeypatch.delenv("TRANSLAY_LLAMA_SERVER", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(llm.shutil, "which", lambda name: None)
    monkeypatch.setattr(llm, "_download", lambda *a, **k: pytest.fail("no debe bajar el zip de Windows"))
    with pytest.raises(RuntimeError, match="TRANSLAY_LLAMA_SERVER"):
        llm.ensure("cpu", tmp_path)


def test_en_windows_sin_variable_usa_las_releases(monkeypatch, tmp_path):
    monkeypatch.delenv("TRANSLAY_LLAMA_SERVER", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    assert llm.installed() is None
    exe = llm.build_dir(tmp_path, "cpu") / "llama-server.exe"
    exe.parent.mkdir(parents=True)
    exe.touch()
    assert llm.ensure("cpu", tmp_path) == exe
