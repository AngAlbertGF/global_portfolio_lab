"""Shared fixtures: temporary databases, deterministic synthetic provider, fixed clock."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from src.analysis import run_analysis
from src.config import AppSettings, load_markets
from src.data_service import DataService
from src.database import Database
from src.synthetic import SyntheticProvider, build_demo_database, demo_portfolio

FIXED_NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def settings(tmp_path):
    return AppSettings(data_dir=str(tmp_path), output_dir=str(tmp_path / "out"), use_demo_database=True)


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def markets():
    return load_markets()


@pytest.fixture
def make_service(db, settings, markets):
    def _make(provider=None, cache_hours=0.0):
        return DataService(db, provider or SyntheticProvider(), markets, settings, now=lambda: FIXED_NOW,
                           cache_hours=cache_hours)
    return _make


@pytest.fixture(scope="session")
def demo_env(tmp_path_factory):
    d = tmp_path_factory.mktemp("demo")
    s = AppSettings(data_dir=str(d), use_demo_database=True, benchmark_ticker="^DEMO-IDX")
    database = Database(d / "demo.db")
    build_demo_database(database, s, load_markets(), now=lambda: FIXED_NOW)
    return database, s


@pytest.fixture(scope="session")
def demo_bundle(demo_env):
    database, s = demo_env
    return run_analysis(database, demo_portfolio(), s, load_markets())


def random_cov(n: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    A = rng.normal(size=(n, n))
    vols = rng.uniform(0.1, 0.4, n)
    C = A @ A.T + n * np.eye(n)
    d = np.sqrt(np.diag(C))
    corr = C / np.outer(d, d)
    return corr * np.outer(vols, vols)


def returns_frame(T: int = 1500, n: int = 5, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    S = random_cov(n, seed) / 252
    mu = rng.uniform(0.0, 0.15, n) / 252
    X = rng.multivariate_normal(mu, S, size=T)
    idx = pd.bdate_range("2015-01-01", periods=T)
    return pd.DataFrame(X, index=idx, columns=[f"A{i}" for i in range(n)])
