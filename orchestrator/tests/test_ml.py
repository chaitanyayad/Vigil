import numpy as np

from vigil.ml.eval import evaluate_predictions, run_eval, static_rule_predictions
from vigil.ml.features import build_features, feature_columns
from vigil.ml.model import score, train_model
from vigil.ml.synth import Incident, generate


def test_synth_shapes_and_labels():
    df, labels, incidents = generate(days=1, seed=1)
    assert len(df) == 1440
    assert labels.shape == (1440,)
    assert set(df.columns) >= {"ts", "cpu_pct", "mem_pct", "disk_pct", "net_rx_bps", "net_tx_bps", "load1"}
    assert (df["cpu_pct"] >= 0).all() and (df["cpu_pct"] <= 100).all()


def test_synth_no_incidents_all_normal():
    _, labels, _ = generate(days=1, seed=2, incidents=[])
    assert labels.sum() == 0


def test_features_columns_and_no_nans():
    df, _, _ = generate(days=1, seed=3, incidents=[])
    features = build_features(df)
    assert list(features.columns) == feature_columns()
    assert not features.isna().any().any()
    assert len(features) == len(df)


def test_model_scores_incident_lower_than_baseline():
    train_df, _, _ = generate(days=2, seed=4, incidents=[])
    eval_df, labels, _ = generate(days=1, seed=5,
                                  incidents=[Incident("cpu_runaway", 700, 60)])
    pipeline = train_model(train_df)
    scores = score(pipeline, eval_df)
    incident_mean = scores[labels == 1].mean()
    normal_mean = scores[labels == 0].mean()
    assert incident_mean < normal_mean, "incident minutes must score more anomalous"


def test_evaluate_predictions_perfect():
    labels = np.zeros(1000, dtype=int)
    labels[100:150] = 1
    m = evaluate_predictions(labels.copy(), labels, [Incident("cpu_runaway", 100, 50)], days=1)
    assert m.precision == 1.0 and m.recall == 1.0 and m.f1 == 1.0
    assert m.mean_detection_delay_min == 0.0
    assert m.false_alarms_per_day == 0.0
    assert m.incidents_detected == 1


def test_evaluate_predictions_counts_false_alarm_episodes():
    labels = np.zeros(1440, dtype=int)
    pred = np.zeros(1440, dtype=int)
    pred[10:15] = 1  # one 5-minute false episode
    pred[100:102] = 1  # another
    m = evaluate_predictions(pred, labels, [], days=1)
    assert m.false_alarms_per_day == 2.0


def test_static_rules_detect_cpu_runaway_after_hold():
    df, labels, _ = generate(days=1, seed=6, incidents=[Incident("cpu_runaway", 700, 60)])
    pred = static_rule_predictions(df, for_minutes=5)
    # fires inside the incident, but not before the 5-minute hold completes
    assert pred[700:704].sum() == 0
    assert pred[704:760].any()


def test_full_eval_ml_beats_rules_on_memory_leak():
    """Phase 2 'done when': anomaly model detects the memory-leak ramp
    >= 10 min earlier than the static thresholds."""
    report = run_eval()
    assert report["ml"]["incidents_detected"] >= 3
    advantage = report["memory_leak_detected_earlier_by_min"]
    assert advantage is not None and advantage >= 10, (
        f"ML must catch the leak >=10 min before static rules, got {advantage}"
    )
