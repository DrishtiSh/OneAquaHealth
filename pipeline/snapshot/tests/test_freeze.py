"""Stage 8 tests: freeze the committed Stage 1-7 outputs into a temp snapshot and check it."""

from __future__ import annotations

import copy
import hashlib

import duckdb
import pytest

from pipeline.common import config
from pipeline.snapshot import freeze_snapshot as fz


@pytest.fixture(scope="module")
def raw():
    try:
        return fz.load_raw_inputs()
    except FileNotFoundError as exc:
        pytest.skip(f"Stage 1-7 outputs missing: {exc}")


@pytest.fixture(scope="module")
def frozen(raw, tmp_path_factory):
    path = tmp_path_factory.mktemp("snap") / "oah_snapshot.duckdb"
    result = fz.freeze(output_path=path)
    con = duckdb.connect(str(path), read_only=True)
    yield result, con
    con.close()


def _tables(raw):
    return fz.build_tables(raw)


# ----------------------------------------------------------------------------- contents


def test_all_tables_and_views_exist_with_expected_rows(frozen):
    result, con = frozen
    tables = {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
    assert set(fz.TABLE_COMMENTS) == tables
    views = {r[0] for r in con.execute("SELECT view_name FROM duckdb_views() WHERE NOT internal").fetchall()}
    assert set(fz.VIEWS) <= views
    n_sites, n_weeks = result["row_counts"]["sites"], result["row_counts"]["weeks"]
    assert result["row_counts"]["scores"] == 2 * n_sites * n_weeks
    assert result["row_counts"]["alert_sensitivity"] == 2 * n_sites * n_weeks * len(config.SENSITIVITY_DELTAS)
    for name in fz.VIEWS:
        assert con.execute(f"SELECT count(*) FROM {name}").fetchone()[0] > 0


def test_both_toggles_are_present(frozen):
    _, con = frozen
    for table in ("scores", "alerts", "incidents"):
        assert {r[0] for r in con.execute(f"SELECT DISTINCT model_variant FROM {table}").fetchall()} == set(fz.VARIANTS)
    levels = {r[0] for r in con.execute("SELECT DISTINCT sensitivity FROM alert_sensitivity").fetchall()}
    assert levels == set(config.SENSITIVITY_DELTAS)


def test_every_table_is_documented(frozen):
    _, con = frozen
    missing = con.execute("SELECT table_name FROM duckdb_tables() WHERE comment IS NULL OR comment = ''").fetchall()
    assert not missing


def test_no_bigint_columns_for_node(frozen):
    """Node's duckdb returns BIGINT as BigInt, which JSON.stringify rejects (Stage 9 regression)."""
    _, con = frozen
    rows = con.execute(
        "SELECT table_name, column_name FROM duckdb_columns() WHERE NOT internal AND data_type = 'BIGINT'"
    ).fetchall()
    assert not rows, rows


def test_manifest_records_health_and_week_range(frozen, raw):
    result, con = frozen
    m = dict(con.execute("SELECT key, value FROM snapshot_manifest").fetchall())
    assert m["snapshot_id"] == result["snapshot_id"] == fz.snapshot_id(raw)
    assert m["diagnostics_passed__M1"] == m["diagnostics_passed__M1_norain"] == "true"
    assert m["latest_week"] == str(max(_tables(raw)["weeks"]["week_start"]))
    assert "not an official health advisory" in m["disclaimer"].lower()
    n_inputs = con.execute("SELECT count(*) FROM snapshot_inputs").fetchone()[0]
    assert n_inputs == len(fz.input_files())


def test_snapshot_id_is_content_addressed(raw):
    assert fz.snapshot_id(raw) == fz.snapshot_id(raw)
    changed = fz.RawInputs(raw.frames, raw.json_docs, {**raw.hashes, "findings": "0" * 64}, raw.paths)
    assert fz.snapshot_id(changed) != fz.snapshot_id(raw)


# ----------------------------------------------------------------------------- privacy & firewall


def test_observations_are_deidentified(frozen):
    _, con = frozen
    cols = {r[0] for r in con.execute("DESCRIBE observations").fetchall()}
    assert not cols & set(fz.DEID_DROP_COLUMNS)
    assert "observed_date" in cols


def test_no_ground_truth_anywhere(frozen):
    _, con = frozen
    cols = {r[0] for r in con.execute("SELECT column_name FROM duckdb_columns() WHERE NOT internal").fetchall()}
    assert not cols & {"W_true", "H_true", "event_id", "contamination_event_active"}
    tables = {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
    assert not any("truth" in t or t == "events" for t in tables)


# ----------------------------------------------------------------------------- guards (raise before writing)


def _truth_column(t, r):
    t["scores"] = t["scores"].assign(W_true=50.0)


def _week_grid(t, r):
    t["scores"] = t["scores"][t["scores"]["week_start"] != t["weeks"]["week_start"].max()]


def _unknown_site(t, r):
    alerts = t["alerts"].copy()
    alerts.loc[alerts.index[0], "site_id"] = "gow-99"
    t["alerts"] = alerts


def _identifying(t, r):
    t["observations"] = t["observations"].assign(observer_id="someone")


def _failed_gate(t, r):
    r.json_docs["diagnostics__M1_norain"]["passed"] = False


def _missing_level(t, r):
    t["alert_sensitivity"] = t["alert_sensitivity"].query("sensitivity != 'strict'")


@pytest.mark.parametrize(
    "mutate, message",
    [
        (_truth_column, "ground-truth"),
        (_week_grid, "different week grid"),
        (_unknown_site, "unknown sites"),
        (_identifying, "identifying"),
        (_failed_gate, "convergence gate"),
        (_missing_level, "lacks levels"),
    ],
)
def test_verify_rejects_inconsistent_inputs(raw, mutate, message):
    r = fz.RawInputs(raw.frames, copy.deepcopy(raw.json_docs), raw.hashes, raw.paths)
    tables = _tables(r)
    mutate(tables, r)
    with pytest.raises(fz.SnapshotError, match=message):
        fz.verify_tables(tables, r)


def test_failed_check_writes_nothing(raw, tmp_path, monkeypatch):
    real_build = fz.build_tables

    def leaky(r):
        t = real_build(r)
        t["alerts"] = t["alerts"].assign(H_true=1.0)
        return t

    monkeypatch.setattr(fz, "build_tables", leaky)
    out = tmp_path / "snap.duckdb"
    with pytest.raises(fz.SnapshotError):
        fz.freeze(output_path=out)
    assert not out.exists() and not (tmp_path / "snap.duckdb.tmp").exists()


def test_failure_mid_write_leaves_previous_snapshot_intact(raw, tmp_path, monkeypatch):
    out = tmp_path / "snap.duckdb"
    fz.freeze(output_path=out)
    before = hashlib.sha256(out.read_bytes()).hexdigest()
    monkeypatch.setattr(fz, "VIEWS", {**fz.VIEWS, "v_broken": "SELECT * FROM no_such_table"})
    with pytest.raises(duckdb.Error):
        fz.freeze(output_path=out)
    assert hashlib.sha256(out.read_bytes()).hexdigest() == before
    assert not (tmp_path / "snap.duckdb.tmp").exists()
