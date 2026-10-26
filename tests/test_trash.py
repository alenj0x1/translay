"""Papelera (vt/trash.py): nada se borra al momento; todo vuelve como estaba.

    python -m pytest tests/test_trash.py
"""

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vt.trash import Trash  # noqa: E402
from vt.vaults import Vaults  # noqa: E402


def _video(vault, vid):
    """Un video con sus archivos: transcripción, voces, audio doblado y descarga."""
    vault.library.data["videos"][vid] = {"id": vid, "title": f"Video {vid}", "source": "youtube", "added": 1}
    r = vault.root
    (r / "transcripts").mkdir(exist_ok=True)
    (r / "transcripts" / f"{vid}.json").write_text("{}", encoding="utf-8")
    for d in ("audio", "voices"):
        (r / d / vid).mkdir(parents=True, exist_ok=True)
        (r / d / vid / "0.wav").write_bytes(b"wav")
    (r / "youtube").mkdir(exist_ok=True)
    (r / "youtube" / f"{vid[3:]}.m4a").write_bytes(b"m4a")


def test_videos_and_clear_go_to_trash_and_come_back():
    with tempfile.TemporaryDirectory() as d:
        vs = Vaults(Path(d) / "data")
        v = vs.create("Comedia")
        for vid in ("yt_aaaaaaaaaaa", "yt_bbbbbbbbbbb"):
            _video(v, vid)
        c = v.library.create("Takataka")
        c["items"] = ["yt_aaaaaaaaaaa"]
        v.library.save()
        tr = Trash(v.root)

        # vaciar: los archivos se mueven (no se borran) y la biblioteca queda vacía
        e = tr.videos(v, list(v.library.data["videos"]), cleared=True)
        v.library.clear()
        assert e["kind"] == "biblioteca-vaciada" and e["count"] == 2
        assert not (v.root / "youtube" / "aaaaaaaaaaa.m4a").exists()
        assert v.library.data == {"videos": {}, "collections": []}
        assert [x["id"] for x in tr.entries()] == [e["id"]]

        # restaurar: videos, colecciones con sus videos y archivos, como estaban
        back = tr.restore_videos(v, e["id"])
        assert sorted(back) == ["yt_aaaaaaaaaaa", "yt_bbbbbbbbbbb"]
        assert (v.root / "youtube" / "aaaaaaaaaaa.m4a").read_bytes() == b"m4a"
        assert (v.root / "voices" / "yt_bbbbbbbbbbb" / "0.wav").exists()
        assert [x["name"] for x in v.library.data["collections"]] == ["Takataka"]
        assert v.library.data["collections"][0]["items"] == ["yt_aaaaaaaaaaa"]
        assert tr.entries() == []

        # borrar un video: vuelve también a la colección en que estaba
        e = tr.videos(v, ["yt_aaaaaaaaaaa"])
        v.library.remove_many(["yt_aaaaaaaaaaa"])
        assert v.library.data["collections"][0]["items"] == []
        tr.restore_videos(v, e["id"])
        assert v.library.data["collections"][0]["items"] == ["yt_aaaaaaaaaaa"]


def test_deleted_vault_is_restorable():
    with tempfile.TemporaryDirectory() as d:
        vs = Vaults(Path(d) / "data")
        v = vs.create("Ciencia")
        _video(v, "yt_ccccccccccc")
        v.library.save()
        root = v.root
        vs.remove(v.id, delete_files=True)
        assert vs.get(v.id) is None and not (root / "library.json").exists()
        main_trash = Trash(vs.main.root)
        (entry,) = main_trash.entries()
        assert entry["kind"] == "biblioteca" and entry["count"] == 1
        e = main_trash.restore_vault_files(entry["id"])
        back = vs.open_folder(e["root"])
        assert back.name == "Ciencia" and "yt_ccccccccccc" in back.library.data["videos"]
        assert (Path(e["root"]) / "youtube" / "ccccccccccc.m4a").exists()


def test_purge_old_and_all():
    with tempfile.TemporaryDirectory() as d:
        vs = Vaults(Path(d) / "data")
        v = vs.create("Vieja")
        _video(v, "yt_ddddddddddd")
        tr = Trash(v.root)
        e = tr.videos(v, ["yt_ddddddddddd"])
        f = tr.dir / e["id"] / "entry.json"
        old = json.loads(f.read_text(encoding="utf-8"))
        old["created"] = time.time() - 31 * 86400
        f.write_text(json.dumps(old), encoding="utf-8")
        assert tr.purge(older_than_days=30) == 1 and tr.entries() == []
        _video(v, "yt_eeeeeeeeeee")
        tr.videos(v, ["yt_eeeeeeeeeee"])
        assert tr.purge() == 0 and tr.purge(tid="") == 0 and len(tr.entries()) == 1  # sin decir qué, nada
        assert tr.purge(everything=True) == 1 and tr.entries() == []


def test_restore_never_overwrites_a_new_copy():
    """Si el video se volvió a importar, restaurar no lo pisa y la entrada queda (hallazgo de la revisión)."""
    with tempfile.TemporaryDirectory() as d:
        vs = Vaults(Path(d) / "data")
        v = vs.create("Uno")
        _video(v, "yt_fffffffffff")
        tr = Trash(v.root)
        e = tr.videos(v, ["yt_fffffffffff"])
        v.library.remove_many(["yt_fffffffffff"])
        _video(v, "yt_fffffffffff")  # importado de nuevo
        try:
            tr.restore_videos(v, e["id"], vs)
            raise AssertionError("debió avisar")
        except ValueError:
            pass
        assert [x["id"] for x in tr.entries()] == [e["id"]]  # la copia vieja sigue en la papelera


def test_restored_vault_does_not_clobber_a_new_one():
    """Eliminar «Ciencia», crear otra «Ciencia» y restaurar la vieja: las dos sobreviven."""
    with tempfile.TemporaryDirectory() as d:
        vs = Vaults(Path(d) / "data")
        old = vs.create("Ciencia")
        _video(old, "yt_ggggggggggg")
        old.library.save()
        vs.remove(old.id, delete_files=True)
        new = vs.create("Ciencia")
        _video(new, "yt_hhhhhhhhhhh")
        new.library.save()
        (entry,) = Trash(vs.main.root).entries()
        e = Trash(vs.main.root).restore_vault_files(entry["id"])
        back = vs.open_folder(e["root"])
        assert e["root"].endswith("-restaurada")
        assert "yt_ggggggggggg" in back.library.data["videos"]
        assert "yt_hhhhhhhhhhh" in vs.get(new.id).library.data["videos"]
