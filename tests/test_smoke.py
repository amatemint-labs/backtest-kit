"""The whole pipeline on the synthetic dataset — the same run as `kit smoke` (about a minute)."""
from kit import config
from kit.smoke import run


def test_smoke_end_to_end(tmp_path):
    s = config.Settings(root=tmp_path, data_dir=tmp_path / "data", studies_dir=tmp_path / "studies")
    res = run(s, log=lambda m: None)
    failed = [c for c in res["checks"] if not c["pass"]]
    assert not failed, failed
    assert res["seconds"] < 240
