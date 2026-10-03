"""Small, dependency-free scoring helpers for the benchmark."""

from __future__ import annotations

import numpy as np
from scipy.stats import rankdata, spearmanr


def _ratio(num: float, den: float) -> float | None:
    return float(num / den) if den else None


def confusion(pred: np.ndarray, truth: np.ndarray) -> dict:
    """Counts plus precision / recall / F1 / false-positive rate (None where undefined)."""
    pred, truth = np.asarray(pred, bool).ravel(), np.asarray(truth, bool).ravel()
    tp = int(np.sum(pred & truth))
    fp = int(np.sum(pred & ~truth))
    fn = int(np.sum(~pred & truth))
    tn = int(np.sum(~pred & ~truth))
    precision = _ratio(tp, tp + fp)
    recall = _ratio(tp, tp + fn)
    if precision is None or recall is None:
        f1 = None
    else:
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall,
            "f1": f1, "false_positive_rate": _ratio(fp, fp + tn)}


def roc_auc(scores: np.ndarray, labels: np.ndarray) -> float | None:
    """Mann-Whitney AUC with tied scores counted as half; None if a class is empty."""
    scores, labels = np.asarray(scores, float).ravel(), np.asarray(labels, bool).ravel()
    n_pos, n_neg = int(labels.sum()), int((~labels).sum())
    if not n_pos or not n_neg:
        return None
    ranks = rankdata(scores)
    return float((ranks[labels].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def average_precision(scores: np.ndarray, labels: np.ndarray) -> float | None:
    """Area under the precision-recall curve (step-wise, ties broken by input order)."""
    scores, labels = np.asarray(scores, float).ravel(), np.asarray(labels, bool).ravel()
    n_pos = int(labels.sum())
    if not n_pos:
        return None
    order = np.argsort(-scores, kind="stable")
    hits = labels[order]
    precision_at_k = np.cumsum(hits) / np.arange(1, len(hits) + 1)
    return float(precision_at_k[hits].sum() / n_pos)


def score_errors(estimate: np.ndarray, q05: np.ndarray, q95: np.ndarray, truth: np.ndarray) -> dict:
    """Point and interval accuracy of a posterior summary against the truth."""
    estimate, q05, q95, truth = (np.asarray(a, float).ravel() for a in (estimate, q05, q95, truth))
    n = len(truth)
    if not n:
        return {"n": 0}
    err = estimate - truth
    rho = spearmanr(estimate, truth).statistic if n > 2 and np.std(truth) > 0 else None
    return {
        "n": n,
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err**2))),
        "bias": float(np.mean(err)),
        "spearman": None if rho is None or np.isnan(rho) else float(rho),
        "coverage_90": float(np.mean((truth >= q05) & (truth <= q95))),
        "mean_interval_width": float(np.mean(q95 - q05)),
    }
