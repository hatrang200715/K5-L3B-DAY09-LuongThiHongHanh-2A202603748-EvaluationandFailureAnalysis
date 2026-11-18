"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def _is_finite(value: object) -> bool:
    try:
        return math.isfinite(value)
    except (TypeError, ValueError, OverflowError):
        return False


def _ratchet_problems(current: dict, previous: dict, collection: str,
                      identifier: str, limits_key: str | None) -> list[str]:
    problems = []
    current_entries = current.get(collection, [])
    previous_entries = previous.get(collection, [])
    if not isinstance(current_entries, list) or not isinstance(previous_entries, list):
        return [f"{collection}: invalid spec entries"]

    def index_entries(entries: list, source: str) -> dict:
        indexed = {}
        for entry in entries:
            if not isinstance(entry, dict) or identifier not in entry:
                problems.append(f"{collection}: invalid {source} entry")
                continue
            entry_id = entry[identifier]
            if entry_id in indexed:
                problems.append(f"{collection}_duplicate:{entry_id}")
            indexed[entry_id] = entry
        return indexed

    current_by_id = index_entries(current_entries, "current")
    previous_by_id = index_entries(previous_entries, "baseline")
    for entry_id, old_entry in previous_by_id.items():
        new_entry = current_by_id.get(entry_id)
        if new_entry is None:
            problems.append(f"{collection}_removed:{entry_id}")
            continue
        if collection == "slices" and new_entry.get("metric") != old_entry.get("metric"):
            problems.append(f"slice_metric_changed:{entry_id}")

        old_limits = old_entry.get(limits_key, {}) if limits_key else old_entry
        new_limits = new_entry.get(limits_key, {}) if limits_key else new_entry
        if not isinstance(old_limits, dict) or not isinstance(new_limits, dict):
            problems.append(f"{collection}_threshold_invalid:{entry_id}")
            continue
        for bound, is_looser in (("min", lambda new, old: new < old),
                                 ("max", lambda new, old: new > old),
                                 ("max_increase", lambda new, old: new > old)):
            if bound not in old_limits:
                continue
            new_value = new_limits.get(bound)
            old_value = old_limits[bound]
            try:
                loosened = new_value is None or not _is_finite(new_value) \
                    or not _is_finite(old_value) or is_looser(new_value, old_value)
            except TypeError:
                loosened = True
            if loosened:
                problems.append(f"{collection}_threshold_loosened:{entry_id}/{bound}")
        if old_limits.get("no_significant_drop") is True \
                and new_limits.get("no_significant_drop") is not True:
            problems.append(f"{collection}_no_significant_drop_removed:{entry_id}")
        if old_entry.get("blocking") is True and new_entry.get("blocking") is not True:
            problems.append(f"{collection}_blocking_removed:{entry_id}")
    return problems


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems = set()
    metrics = pr.get("metrics")
    if not isinstance(metrics, dict):
        problems.add("pr.metrics_missing_or_invalid")
    else:
        for metric, value in metrics.items():
            if value is not None and not _is_finite(value):
                problems.add(f"non_finite_metric:{metric}")

    def index_rows(report: dict, label: str) -> tuple[dict, list]:
        rows = report.get("rows")
        if not isinstance(rows, list):
            problems.add(f"{label}.rows_missing_or_invalid")
            return {}, []
        indexed = {}
        for row in rows:
            if not isinstance(row, dict) or row.get("item_id") is None or row.get("seed") is None:
                problems.add(f"{label}.row_missing_item_or_seed")
                continue
            key = (row["item_id"], row["seed"])
            try:
                if key in indexed:
                    problems.add(f"{label}.duplicate_row:{key[0]}@{key[1]}")
                indexed[key] = row
            except TypeError:
                problems.add(f"{label}.invalid_row_key")
        return indexed, rows

    pr_rows, pr_row_list = index_rows(pr, "pr")
    base_rows, _ = index_rows(base, "base")
    pr_manifest = pr.get("manifest")
    if not isinstance(pr_manifest, dict):
        problems.add("pr.manifest_missing_or_invalid")
    else:
        if not pr_manifest.get("eval_set_sha"):
            problems.add("pr.eval_set_sha_missing")
        item_count = pr_manifest.get("items")
        seeds = pr_manifest.get("seeds")
        if not isinstance(item_count, int) or item_count < 0 or not isinstance(seeds, list):
            problems.add("pr.manifest_items_or_seeds_invalid")
        else:
            try:
                duplicate_seeds = len(seeds) != len(set(seeds))
            except TypeError:
                duplicate_seeds = True
            if duplicate_seeds:
                problems.add("pr.manifest_seeds_duplicated_or_invalid")
            expected_rows = item_count * len(seeds)
            if len(pr_row_list) != expected_rows:
                problems.add(f"pr.row_count:{len(pr_row_list)}!={expected_rows}")
            try:
                if len({item for item, _ in pr_rows}) != item_count:
                    problems.add("pr.item_count_mismatch")
                if {seed for _, seed in pr_rows} != set(seeds):
                    problems.add("pr.seed_set_mismatch")
            except TypeError:
                problems.add("pr.manifest_or_row_keys_invalid")
    base_manifest = base.get("manifest")
    if not isinstance(base_manifest, dict) or not base_manifest.get("eval_set_sha"):
        problems.add("base.manifest_or_eval_set_sha_missing")

    if set(pr_rows) != set(base_rows):
        problems.add("item_seed_set_mismatch")

    evaluator_failures = pr.get("evaluator_failures")
    if not isinstance(evaluator_failures, list):
        problems.add("pr.evaluator_failures_missing_or_invalid")
    elif evaluator_failures:
        problems.add("pr.evaluator_failures")

    per_trial_metrics = {
        metric["id"] for metric in spec.get("metrics", [])
        if isinstance(metric, dict) and "id" in metric
        and metric.get("grader") != "lab8.metrics.summarize"
    }
    for key, row in pr_rows.items():
        for metric in per_trial_metrics:
            value = row.get(metric)
            if value is None:
                problems.add(f"missing_row_metric:{metric}:{key[0]}@{key[1]}")
            elif not _is_finite(value):
                problems.add(f"non_finite_row_metric:{metric}:{key[0]}@{key[1]}")

    def slice_tags(row: dict, label: str, key: tuple) -> tuple[str, ...]:
        tags = row.get("slices") or []
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            problems.add(f"{label}.invalid_slice_tags:{key[0]}@{key[1]}")
            return ()
        return tuple(sorted(set(tags)))

    for key in set(pr_rows) & set(base_rows):
        if slice_tags(pr_rows[key], "pr", key) != slice_tags(base_rows[key], "base", key):
            problems.add(f"slice_tags_changed:{key[0]}")

    version = spec.get("eval_set_version")
    if base_spec is not None and version is not None and version == base_spec.get("eval_set_version"):
        problems.update(_ratchet_problems(spec, base_spec, "metrics", "id", "threshold"))
        problems.update(_ratchet_problems(spec, base_spec, "slices", "name", None))
    return sorted(problems)


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bootstrap = spec.get("bootstrap", {})
    for slice_spec in spec.get("slices", []):
        name, metric = slice_spec["name"], slice_spec["metric"]
        identifier = f"slice:{name}/{metric}"
        pr_items = per_item(pr, metric, slice_name=name)
        base_items = per_item(base, metric, slice_name=name)
        value = sum(pr_items.values()) / len(pr_items) if pr_items else None
        failures, notes = [], []

        if value is None:
            failures.append("missing PR slice data")
        else:
            if "min" in slice_spec and value < slice_spec["min"]:
                failures.append(f"below min {slice_spec['min']}")
            if "max" in slice_spec and value > slice_spec["max"]:
                failures.append(f"above max {slice_spec['max']}")

        if slice_spec.get("no_significant_drop"):
            if set(pr_items) != set(base_items) or not pr_items:
                failures.append("paired slice data unavailable")
            else:
                item_ids = sorted(pr_items)
                difference, low, high = stats.paired_bootstrap(
                    [pr_items[item] for item in item_ids],
                    [base_items[item] for item in item_ids],
                    n_resamples=bootstrap.get("n_resamples", 1000),
                    rng=bootstrap.get("rng", 2027),
                    confidence=bootstrap.get("confidence", 0.95),
                )
                notes.append(f"Δ {difference:+.3f} CI [{low:+.3f}, {high:+.3f}]")
                if high < 0:
                    failures.append("significant drop")

        is_blocking = bool(slice_spec.get("blocking"))
        if failures and is_blocking:
            blocked.append(identifier)
        verdict = "BLOCK" if failures and is_blocking else "warn" if failures else "ok"
        mean_text = "MISSING" if value is None else f"{value:.4f}"
        detail = ", ".join(failures)
        note = "; ".join(notes)
        lines.append(
            f"  {identifier:<38} {mean_text:<8} {detail:<28} {note:<28} {verdict}"
        )
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
