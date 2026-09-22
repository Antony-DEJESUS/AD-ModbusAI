"""Mode d'emploi PDF : trouvé dans le dépôt, choisi par version, embarqué par le spec."""

from pathlib import Path

from modbusai.ui import resources

ROOT = Path(__file__).resolve().parent.parent


def test_manual_is_found_in_repository():
    path = resources.manual_pdf_path()
    assert path is not None and path.exists() and path.suffix == ".pdf"
    # Hors PyInstaller, le lecteur reçoit le fichier du dépôt, sans copie.
    assert resources.manual_for_viewer() == path


def test_newest_manual_wins_numerically(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    for version in ("1.9.0", "1.10.0", "1.2.5"):
        (docs / f"AD-ModbusAI_Mode_d_emploi_v{version}.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(resources, "project_root", lambda: tmp_path)
    monkeypatch.setattr(resources, "__version__", "2.0.0")
    assert resources.manual_pdf_path().name.endswith("_v1.10.0.pdf")
    monkeypatch.setattr(resources, "__version__", "1.2.5")
    assert resources.manual_pdf_path().name.endswith("_v1.2.5.pdf")


def test_missing_manual_gives_none(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "project_root", lambda: tmp_path)
    assert resources.manual_pdf_path() is None


def test_bundled_manual_is_copied_out_of_the_temporary_bundle(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    (bundle / "docs").mkdir(parents=True)
    (bundle / "docs" / "AD-ModbusAI_Mode_d_emploi_v1.1.0.pdf").write_bytes(b"%PDF-1.7")
    monkeypatch.setattr(resources, "project_root", lambda: bundle)
    monkeypatch.setattr(resources.sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(resources.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    copy = resources.manual_for_viewer()
    assert copy is not None and bundle not in copy.parents
    assert copy.read_bytes() == b"%PDF-1.7"


def test_spec_embeds_the_manual():
    spec = (ROOT / "packaging" / "modbusai.spec").read_text(encoding="utf-8")
    assert '(str(MANUAL), "docs")' in spec
