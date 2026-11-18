"""M5-M7 self-check (Advanced/Expert). Run: python -m pytest -q -m student -o addopts= -k advanced
Public vectors only; the instructor grades with hidden ones."""
import copy
import math

import pytest

pytestmark = pytest.mark.student


@pytest.fixture(scope="module")
def stats():
    from lab9 import stats

    return stats


@pytest.mark.parametrize("n,c,k,want", [(5, 5, 5, 1.0), (5, 0, 1, 0.0), (5, 2, 1, 0.4), (10, 3, 3, 1 - 35 / 120)])
def test_pass_at_k(stats, n, c, k, want):
    assert math.isclose(stats.pass_at_k(n, c, k), want, abs_tol=1e-9)


@pytest.mark.parametrize("n,c,k,want", [(5, 5, 5, 1.0), (5, 4, 5, 0.0), (5, 4, 3, 0.4), (10, 8, 2, 28 / 45)])
def test_pass_hat_k(stats, n, c, k, want):
    assert math.isclose(stats.pass_hat_k(n, c, k), want, abs_tol=1e-9)


def test_pass_k_rejects_bad_args(stats):
    for args in [(5, 6, 1), (5, 2, 0), (3, 1, 4)]:
        with pytest.raises(ValueError):
            stats.pass_at_k(*args)


def _report(rows, metrics, items=4, seeds=(1, 2)):
    return {"manifest": {"eval_set_sha": "x", "items": items, "seeds": list(seeds)},
            "rows": rows, "metrics": metrics, "evaluator_failures": []}


ROWS = [{"item_id": f"E-{i:03d}", "seed": s, "pass_rate": True, "slices": ["denial"] if i < 2 else []}
        for i in range(4) for s in (1, 2)]
SPEC = {"eval_set_version": "v2", "metrics": [{"id": "pass_rate", "kind": "capability", "blocking": True,
                                               "threshold": {"min": 0.8}}]}


def test_integrity_flags_nan_and_dropped_rows():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    assert gate.integrity_check(base, base, SPEC) == []
    nan = _report(copy.deepcopy(ROWS), {"pass_rate": float("nan")})
    assert gate.integrity_check(nan, base, SPEC)
    dropped = _report(copy.deepcopy(ROWS[:-1]), {"pass_rate": 1.0})
    assert gate.integrity_check(dropped, base, SPEC)


def test_check_blocks_missing_manifest_without_crashing():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    pr = copy.deepcopy(base)
    del pr["manifest"]
    blocked, lines = gate.check(pr, base, SPEC)
    assert blocked == ["integrity"]
    assert any("manifest" in line for line in lines)


def test_integrity_flags_missing_grader_values_and_relabelled_slices():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    missing = copy.deepcopy(base)
    missing["rows"][0]["pass_rate"] = None
    assert any("missing_row_metric:pass_rate" in p
               for p in gate.integrity_check(missing, base, SPEC))

    relabelled = copy.deepcopy(base)
    relabelled["rows"][0]["slices"] = []
    assert any("slice_tags_changed:E-000" in p
               for p in gate.integrity_check(relabelled, base, SPEC))


def test_integrity_flags_loosened_spec():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    loose = copy.deepcopy(SPEC)
    loose["metrics"][0]["threshold"]["min"] = 0.5
    assert gate.integrity_check(base, base, loose, SPEC)
    assert gate.integrity_check(base, base, SPEC, SPEC) == []


def test_integrity_ratchets_metrics_and_slices():
    from lab9 import gate

    base_spec = copy.deepcopy(SPEC)
    base_spec["metrics"][0]["threshold"]["no_significant_drop"] = True
    base_spec["slices"] = [
        {"name": "denial", "metric": "pass_rate", "min": 0.9,
         "no_significant_drop": True, "blocking": True}
    ]
    loose_spec = copy.deepcopy(base_spec)
    loose_spec["metrics"].pop()
    loose_spec["slices"][0]["min"] = 0.8
    loose_spec["slices"][0].pop("no_significant_drop")
    loose_spec["slices"][0]["blocking"] = False

    report = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    problems = gate.integrity_check(report, report, loose_spec, base_spec)
    assert any("metrics_removed:pass_rate" in p for p in problems)
    assert any("slices_threshold_loosened:denial/min" in p for p in problems)
    assert any("slices_no_significant_drop_removed:denial" in p for p in problems)
    assert any("slices_blocking_removed:denial" in p for p in problems)


def test_slice_check_blocks_a_slice_below_floor():
    from lab9 import gate

    base = _report(copy.deepcopy(ROWS), {"pass_rate": 1.0})
    rows = copy.deepcopy(ROWS)
    for r in rows:
        if "denial" in r["slices"] and r["seed"] == 1:
            r["pass_rate"] = False
    spec = dict(SPEC, slices=[{"name": "denial", "metric": "pass_rate", "min": 0.9, "blocking": True}])
    blocked, _ = gate.slice_check(_report(rows, {"pass_rate": 0.75}), base, spec)
    assert blocked == ["slice:denial/pass_rate"]


def test_slice_check_blocks_significant_drop_even_above_floor():
    from lab9 import gate

    base_rows = copy.deepcopy(ROWS)
    pr_rows = copy.deepcopy(ROWS)
    for row in pr_rows:
        if "denial" in row["slices"]:
            row["pass_rate"] = 0.5
    base = _report(base_rows, {"pass_rate": 1.0})
    pr = _report(pr_rows, {"pass_rate": 0.75})
    spec = dict(SPEC, slices=[
        {"name": "denial", "metric": "pass_rate", "min": 0.4,
         "no_significant_drop": True, "blocking": True}
    ])

    blocked, lines = gate.slice_check(pr, base, spec)
    assert blocked == ["slice:denial/pass_rate"]
    assert "significant drop" in lines[0]
