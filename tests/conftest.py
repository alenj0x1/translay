"""Las pruebas no dependen del idioma de Windows de quien las corre: el «sistema» es español, como la app de siempre."""

import pytest


@pytest.fixture(autouse=True)
def _system_language_es(monkeypatch):
    from vt import langs

    monkeypatch.setattr(langs, "system", lambda: "es")
    langs.set_ui("es")
    langs.set_target("es")
    yield
    langs.set_ui("es")
    langs.set_target("es")
