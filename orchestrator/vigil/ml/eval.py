"""Evaluation harness: anomaly model vs static threshold rules on the labelled
synthetic set. Reproducible with one command:

    python -m vigil.ml.eval            # prints JSON report + markdown table
"""

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from vigil.ml.model import score, smooth_predictions, train_model
from vigil.ml.synth import Incident, generate


@dataclass
class EvalMetrics:
    precision: float
    recall: float
    f1: float
    mean_detection_delay_min: float | None
    false_alarms_per_day: float
    incidents_detected: int
    incidents_total: int

    def as_dict(self) -> dict:
        return {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "mean_detection_delay_min": (
                None if self.mean_detection_delay_min is None
                else round(self.mean_detection_delay_min, 1)
            ),
            "false_alarms_per_day": round(self.false_alarms_per_day, 2),
            "incidents_detected": self.incidents_detected,
            "incidents_total": self.incidents_total,
        }


def evaluate_predictions(
    predictions: np.ndarray, labels: np.ndarray, incidents: list[Incident], days: float
) -> EvalMetrics:
    predictions = predictions.astype(bool)
    labels = labels.astype(bool)
    tp = int(np.sum(predictions & labels))
    fp = int(np.sum(predictions & ~labels))
    fn = int(np.sum(~predictions & labels))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    delays: list[float] = []
    detected = 0
    for inc in incidents:
        window = predictions[inc.start_min : inc.start_min + inc.duration_min]
        hits = np.flatnonzero(window)
        if hits.size:
            detected += 1
            delays.append(float(hits[0]))

    # False-alarm episodes: runs of consecutive FP minutes outside any incident
    fp_mask = predictions & ~labels
    episodes = int(np.sum(fp_mask[1:] & ~fp_mask[:-1]) + (1 if fp_mask[0] else 0))

    return EvalMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        mean_detection_delay_min=(sum(delays) / len(delays)) if delays else None,
        false_alarms_per_day=episodes / days,
        incidents_detected=detected,
        incidents_total=len(incidents),
    )


def static_rule_predictions(df: pd.DataFrame, for_minutes: int = 5) -> np.ndarray:
    """A reasonable static-threshold ruleset (Sentinel-style) applied offline:
    fires when a threshold has held for `for_minutes` consecutive minutes."""
    conditions = (
        (df["cpu_pct"].to_numpy() > 85)
        | (df["mem_pct"].to_numpy() > 90)
        | (df["disk_pct"].to_numpy() > 90)
        | (df["net_rx_bps"].to_numpy() > 100e6)
    )
    out = np.zeros(len(df), dtype=bool)
    run = 0
    for i, c in enumerate(conditions):
        run = run + 1 if c else 0
        if run >= for_minutes:
            out[i] = True
    return out


def run_eval(seed_train: int = 7, seed_eval: int = 42) -> dict:
    # Train on clean baseline (no incidents), evaluate on the incident set
    train_df, _, _ = generate(days=6, seed=seed_train, incidents=[])
    eval_df, labels, incidents = generate(days=6, seed=seed_eval)
    days = len(eval_df) / 1440.0

    model = train_model(train_df)
    scores = score(model, eval_df)
    # Same calibrated threshold + consecutive-minute streak as live inference
    ml_pred = smooth_predictions(scores, model.threshold)
    threshold = model.threshold
    ml_metrics = evaluate_predictions(ml_pred, labels, incidents, days)
    rule_pred = static_rule_predictions(eval_df)
    rule_metrics = evaluate_predictions(rule_pred, labels, incidents, days)

    # Head-to-head on the memory leak: how much earlier does ML catch the ramp?
    leak = next((i for i in incidents if i.kind == "memory_leak"), None)
    leak_advantage = None
    if leak:
        def first_hit(pred):
            window = pred[leak.start_min : leak.start_min + leak.duration_min]
            hits = np.flatnonzero(window)
            return int(hits[0]) if hits.size else None

        ml_hit, rule_hit = first_hit(ml_pred), first_hit(rule_pred)
        if ml_hit is not None:
            leak_advantage = (rule_hit - ml_hit) if rule_hit is not None else leak.duration_min - ml_hit

    return {
        "threshold": round(threshold, 5),
        "ml": ml_metrics.as_dict(),
        "static_rules": rule_metrics.as_dict(),
        "memory_leak_detected_earlier_by_min": leak_advantage,
    }


def markdown_table(report: dict) -> str:
    ml, rules = report["ml"], report["static_rules"]
    rows = [
        ("Precision", ml["precision"], rules["precision"]),
        ("Recall", ml["recall"], rules["recall"]),
        ("F1", ml["f1"], rules["f1"]),
        ("Mean detection delay (min)", ml["mean_detection_delay_min"], rules["mean_detection_delay_min"]),
        ("False alarms / day", ml["false_alarms_per_day"], rules["false_alarms_per_day"]),
        ("Incidents detected", f"{ml['incidents_detected']}/{ml['incidents_total']}",
         f"{rules['incidents_detected']}/{rules['incidents_total']}"),
    ]
    lines = ["| Metric | IsolationForest | Static rules |", "|---|---|---|"]
    lines += [f"| {name} | {a} | {b} |" for name, a, b in rows]
    lines.append(
        f"\nMemory-leak ramp detected **{report['memory_leak_detected_earlier_by_min']} min earlier** "
        "than the static ruleset."
    )
    return "\n".join(lines)


if __name__ == "__main__":
    report = run_eval()
    print(json.dumps(report, indent=2))
    print()
    print(markdown_table(report))
