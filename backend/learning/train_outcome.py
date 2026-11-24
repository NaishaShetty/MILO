"""
train_outcome.py (backend/learning)

Trains and evaluates the step outcome predictor from `data/dataset/*.csv`:

    cd backend
    python -m learning.train_outcome --data data/dataset --out artifacts/outcome

Targets: P(step succeeds), expected duration, P(a retry would succeed), most
likely failure type. Models: gradient-boosted trees (scikit-learn's
HistGradientBoosting -- LightGBM needs an OpenMP system library this
environment lacks) with isotonic calibration fitted on the validation split;
then a small PyTorch MLP on the same features, kept only if it beats the trees
on the held-out *test scenes*. Baselines: majority class and a hand-written
rule (what the rule-based side can know: is the target in reach / in view).

Writes `<out>/<version>/{model.pkl,metrics.json}` and appends to
`artifacts/registry.json` (name, version, data hash, metrics, date).
"""

from __future__ import annotations

import argparse
import csv
import json
import pickle
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)
from sklearn.isotonic import IsotonicRegression

from learning.metrics import binary_report
from learning.predictor_features import FEATURE_NAMES, context_from_row, featurize
from learning.schema import FAILURE_TYPES

SEED = 0
FAIL_TYPES = [t for t in FAILURE_TYPES if t != "none"]


def load_rows(path: Path) -> List[Dict[str, Any]]:
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


def retry_labels(rows: List[Dict[str, Any]]) -> Dict[int, int]:
    """For each failed row index: 1 if the same (action, target) step succeeded
    in a later attempt of the same episode (a retry/replan worked), else 0."""
    by_episode: Dict[str, List[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        by_episode[r["episode_id"]].append(i)
    out: Dict[int, int] = {}
    for idxs in by_episode.values():
        for i in idxs:
            r = rows[i]
            if r["success"] != "0":
                continue
            later = [
                rows[j]
                for j in idxs
                if int(rows[j]["attempt"]) > int(r["attempt"])
                and rows[j]["action"] == r["action"]
                and rows[j]["target"] == r["target"]
            ]
            out[i] = int(any(x["success"] == "1" for x in later))
    return out


def build_xy(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    X = np.array([featurize(context_from_row(r)) for r in rows], dtype=np.float64)
    y = np.array([int(r["success"]) for r in rows])
    dur = np.array(
        [
            float(r["duration_ms"]) if r["duration_ms"] not in ("", None) else 0.0
            for r in rows
        ]
    )
    rl = retry_labels(rows)
    fail_idx = np.array(sorted(rl))
    ftype = np.array(
        [
            (
                FAIL_TYPES.index(rows[i]["failure_type"])
                if rows[i]["failure_type"] in FAIL_TYPES
                else len(FAIL_TYPES) - 1
            )
            for i in fail_idx
        ]
    )
    return {
        "X": X,
        "y": y,
        "dur": dur,
        "fail_idx": fail_idx,
        "retry_y": np.array([rl[i] for i in fail_idx]),
        "ftype": ftype,
    }


def rule_baseline(rows: List[Dict[str, Any]]) -> np.ndarray:
    """What hand-written rules can say about a step: proximity actions need the
    target in reach, perceiving/walking needs it to exist and be in view."""
    out = []
    for r in rows:
        ctx = context_from_row(r)
        if ctx["action"] in ("pickup", "place", "open", "close", "turn_on", "turn_off"):
            out.append(0.9 if ctx["reachable"] else 0.1)
        elif ctx["action"] in ("navigate", "locate"):
            out.append(0.9 if ctx["target_found"] and ctx["visible"] else 0.1)
        else:
            out.append(0.9)
    return np.array(out)


def fit_isotonic(p_val: np.ndarray, y_val: np.ndarray) -> IsotonicRegression:
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    return iso.fit(p_val, y_val)


def train_mlp(Xtr, ytr, Xva, yva, epochs: int = 60):
    import torch
    from torch import nn

    torch.manual_seed(SEED)
    mean, std = Xtr.mean(0), Xtr.std(0) + 1e-6
    net = nn.Sequential(
        nn.Linear(Xtr.shape[1], 64),
        nn.ReLU(),
        nn.Linear(64, 32),
        nn.ReLU(),
        nn.Linear(32, 1),
    )
    opt = torch.optim.Adam(net.parameters(), lr=3e-3, weight_decay=1e-5)
    loss_fn = nn.BCEWithLogitsLoss()
    xt = torch.tensor((Xtr - mean) / std, dtype=torch.float32)
    yt = torch.tensor(ytr, dtype=torch.float32)
    xv = torch.tensor((Xva - mean) / std, dtype=torch.float32)
    best, best_state = 1e9, None
    for _ in range(epochs):
        perm = torch.randperm(len(xt))
        for i in range(0, len(xt), 256):
            idx = perm[i : i + 256]
            opt.zero_grad()
            loss = loss_fn(net(xt[idx]).squeeze(1), yt[idx])
            loss.backward()
            opt.step()
        with torch.no_grad():
            v = loss_fn(
                net(xv).squeeze(1), torch.tensor(yva, dtype=torch.float32)
            ).item()
        if v < best:
            best, best_state = v, {k: t.clone() for k, t in net.state_dict().items()}
    assert best_state is not None
    net.load_state_dict(best_state)
    return net, mean, std


def mlp_predict(net, mean, std, X) -> np.ndarray:
    import torch

    with torch.no_grad():
        return torch.sigmoid(
            net(torch.tensor((X - mean) / std, dtype=torch.float32)).squeeze(1)
        ).numpy()


def tune_thresholds(
    val: Dict[str, Any],
    p_succ_val: np.ndarray,
    p_retry_val: np.ndarray,
    val_rows: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Decision thresholds tuned on the validation split.
    - `retry`: the cut on P(retry succeeds) maximising balanced accuracy;
    - `abort`: the largest cut on P(step succeeds) such that, among failed
      steps scoring below it, >= 95% belonged to missions that never recovered."""
    y = val["retry_y"]
    best_t, best_s = 0.5, -1.0
    for t in np.linspace(0.05, 0.95, 19):
        pred = p_retry_val >= t
        tpr = (pred & (y == 1)).sum() / max((y == 1).sum(), 1)
        tnr = (~pred & (y == 0)).sum() / max((y == 0).sum(), 1)
        if (tpr + tnr) / 2 > best_s:
            best_s, best_t = (tpr + tnr) / 2, float(t)
    fail_rows = [val_rows[i] for i in val["fail_idx"]]
    doomed = np.array([r["episode_outcome"] != "succeeded" for r in fail_rows])
    p_fail = p_succ_val[val["fail_idx"]]
    abort_t = 0.0
    for t in np.linspace(0.02, 0.5, 25):
        below = p_fail < t
        if below.sum() >= 20 and doomed[below].mean() >= 0.95:
            abort_t = float(t)
    return {"retry": best_t, "abort": abort_t}


def importances(model, X, y, names: List[str], top: int = 12) -> Dict[str, float]:
    """Permutation importance (drop in accuracy when a feature is shuffled)."""
    rng = np.random.default_rng(SEED)
    base = ((model.predict_proba(X)[:, 1] >= 0.5) == y).mean()
    scores = {}
    for j, name in enumerate(names):
        Xp = X.copy()
        Xp[:, j] = rng.permutation(Xp[:, j])
        scores[name] = float(
            base - ((model.predict_proba(Xp)[:, 1] >= 0.5) == y).mean()
        )
    return dict(sorted(scores.items(), key=lambda kv: -kv[1])[:top])


def train(data: Path, out: Path, registry: Optional[Path] = None) -> Dict[str, Any]:
    tr, va, te = (load_rows(data / f"{n}.csv") for n in ("train", "val", "test"))
    D = {n: build_xy(r) for n, r in (("train", tr), ("val", va), ("test", te))}
    Xtr, ytr = D["train"]["X"], D["train"]["y"]

    clf = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.08, random_state=SEED
    ).fit(Xtr, ytr)
    iso = fit_isotonic(clf.predict_proba(D["val"]["X"])[:, 1], D["val"]["y"])

    def p_success(X):
        return iso.predict(clf.predict_proba(X)[:, 1])

    reg = HistGradientBoostingRegressor(max_iter=150, random_state=SEED).fit(
        Xtr, D["train"]["dur"]
    )

    def sub(name):
        idx = D[name]["fail_idx"]
        return D[name]["X"][idx], D[name]["retry_y"], D[name]["ftype"]

    Xf, yr, ft = sub("train")
    retry_clf = HistGradientBoostingClassifier(max_iter=120, random_state=SEED).fit(
        Xf, yr
    )
    Xfv, yrv, _ = sub("val")
    retry_iso = fit_isotonic(retry_clf.predict_proba(Xfv)[:, 1], yrv)
    type_clf = HistGradientBoostingClassifier(max_iter=120, random_state=SEED).fit(
        Xf, ft
    )

    # ---- test-scene evaluation -------------------------------------------------
    Xte, yte = D["test"]["X"], D["test"]["y"]
    p_tree = p_success(Xte)
    prior = float(ytr.mean())
    metrics: Dict[str, Any] = {
        "trees": binary_report(yte, p_tree),
        "baseline_majority": binary_report(yte, np.full(len(yte), prior)),
        "baseline_rules": binary_report(yte, rule_baseline(te)),
    }
    dur_pred = reg.predict(Xte)
    metrics["duration"] = {
        "mae_ms": float(np.abs(dur_pred - D["test"]["dur"]).mean()),
        "baseline_mean_mae_ms": float(
            np.abs(D["train"]["dur"].mean() - D["test"]["dur"]).mean()
        ),
    }
    Xtf, ytr_test, ftt = sub("test")
    p_retry_te = retry_iso.predict(retry_clf.predict_proba(Xtf)[:, 1])
    metrics["retry_success"] = {
        "trees": binary_report(ytr_test, p_retry_te),
        "baseline_majority": binary_report(
            ytr_test, np.full(len(ytr_test), float(yr.mean()))
        ),
    }
    type_acc = float((type_clf.predict(Xtf) == ftt).mean())
    majority = int(np.bincount(ft).argmax())
    metrics["failure_type"] = {
        "accuracy": type_acc,
        "baseline_majority_accuracy": float((ftt == majority).mean()),
        "n": int(len(ftt)),
    }

    # ---- MLP: keep only if it beats the trees on held-out scenes ---------------
    net, mean, std = train_mlp(Xtr, ytr, D["val"]["X"], D["val"]["y"])
    mlp_val = mlp_predict(net, mean, std, D["val"]["X"])
    mlp_iso = fit_isotonic(mlp_val, D["val"]["y"])
    p_mlp = mlp_iso.predict(mlp_predict(net, mean, std, Xte))
    metrics["mlp"] = binary_report(yte, p_mlp)
    t, m = metrics["trees"], metrics["mlp"]
    keep_mlp = (m["auroc"] or 0) > (t["auroc"] or 0) + 0.005 and m["ece"] <= t[
        "ece"
    ]  # margin: not noise
    metrics["mlp_kept"] = bool(keep_mlp)
    metrics["note"] = (
        "MLP kept"
        if keep_mlp
        else "MLP did not beat the trees by a clear margin on held-out scenes; trees are served"
    )

    thresholds = tune_thresholds(
        D["val"],
        p_success(D["val"]["X"]),
        _full_retry(D["val"], retry_clf, retry_iso),
        va,
    )
    metrics["thresholds"] = thresholds
    metrics["feature_importance"] = importances(
        clf, D["val"]["X"][:3000], D["val"]["y"][:3000], FEATURE_NAMES
    )

    version = time.strftime("%Y%m%d-%H%M%S")
    run = out / version
    run.mkdir(parents=True, exist_ok=True)
    artifact = {
        "version": version,
        "feature_names": FEATURE_NAMES,
        "success_clf": clf,
        "success_iso": iso,
        "duration_reg": reg,
        "retry_clf": retry_clf,
        "retry_iso": retry_iso,
        "type_clf": type_clf,
        "fail_types": FAIL_TYPES,
        "thresholds": thresholds,
        "train_mean": Xtr.mean(0),
        "train_std": Xtr.std(0) + 1e-6,
        "importance": metrics["feature_importance"],
        "mlp": (net.state_dict(), mean, std, mlp_iso) if keep_mlp else None,
    }
    with open(run / "model.pkl", "wb") as handle:
        pickle.dump(artifact, handle)
    manifest = (
        json.loads((data / "manifest.json").read_text())
        if (data / "manifest.json").exists()
        else {}
    )
    entry = {
        "name": "outcome_predictor",
        "version": version,
        "data_hash": manifest.get("data_hash"),
        "date": time.strftime("%Y-%m-%d"),
        "train_steps": int(len(ytr)),
        "metrics": {
            "auroc": t["auroc"],
            "pr_auc": t["pr_auc"],
            "brier": t["brier"],
            "ece": t["ece"],
        },
        "path": str(run / "model.pkl"),
    }
    (run / "metrics.json").write_text(
        json.dumps({**metrics, "registry": entry}, indent=2)
    )
    registry = registry or out.parent / "registry.json"
    reg_data = json.loads(registry.read_text()) if registry.exists() else {"models": []}
    reg_data["models"].append(entry)
    registry.write_text(json.dumps(reg_data, indent=2))
    return {**metrics, "registry": entry}


def _full_retry(split: Dict[str, Any], retry_clf, retry_iso) -> np.ndarray:
    """P(retry succeeds) for the failed rows of a split, aligned with `fail_idx`."""
    idx = split["fail_idx"]
    return retry_iso.predict(retry_clf.predict_proba(split["X"][idx])[:, 1])


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", type=Path, default=Path("data/dataset"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/outcome"))
    args = parser.parse_args(argv)
    m = train(args.data, args.out)
    t = m["trees"]
    print(
        json.dumps(
            {k: m[k] for k in ("duration", "failure_type", "thresholds", "note")},
            indent=2,
        )
    )
    for name in ("trees", "mlp", "baseline_rules", "baseline_majority"):
        r = m[name]
        print(
            f"{name:18s} AUROC={r['auroc']:.3f} PR-AUC={r['pr_auc']:.3f} Brier={r['brier']:.4f} ECE={r['ece']:.4f}"
        )
    print("registered:", m["registry"]["version"], "ECE", round(t["ece"], 4))


if __name__ == "__main__":
    main()
