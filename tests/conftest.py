import os

import pytest

os.environ["KIT_SECRETS"] = "memory"      # tests never touch the real Keychain or .env


@pytest.fixture(scope="session")
def synthetic_store(tmp_path_factory):
    """Eight months of synthetic bars, all timeframes, in a temp folder."""
    from kit.data import synthetic
    d = tmp_path_factory.mktemp("store")
    synthetic.build(d, ["3m", "15m", "1h", "4h", "1D"], start="2025-08-01", end="2026-03-31")
    return d
