"""IsolationForest train / persist / score.

An artifact is {pipeline, threshold}: the anomaly threshold is calibrated per
model as the 0.5th percentile of its own training scores (raw IsolationForest
decision_function values compress toward 0, so a fixed global threshold does
not transfer between models). Production inference additionally requires
CONSECUTIVE_ANOMALOUS_MINUTES below threshold before firing.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from vigil.core.config import get_settings
from vigil.ml.features import build_features

THRESHOLD_PERCENTILE = 0.5
CONSECUTIVE_ANOMALOUS_MINUTES = 3


@dataclass
class AnomalyModel:
    pipeline: Pipeline
    threshold: float


def train_model(df: pd.DataFrame) -> AnomalyModel:
    """df: 1-minute samples (ts + metric columns). Fits scaler + IsolationForest
    and calibrates the score threshold on the training distribution."""
    features = build_features(df).to_numpy()
    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "forest",
                IsolationForest(
                    n_estimators=200,
                    max_samples=min(2048, len(features)),
                    random_state=17,
                    n_jobs=-1,
                ),
            ),
        ]
    )
    pipeline.fit(features)
    train_scores = pipeline.decision_function(features)
    threshold = float(np.percentile(train_scores, THRESHOLD_PERCENTILE))
    return AnomalyModel(pipeline=pipeline, threshold=threshold)


def score(model: AnomalyModel, df: pd.DataFrame) -> np.ndarray:
    """decision_function scores: negative = more anomalous."""
    return model.pipeline.decision_function(build_features(df).to_numpy())


def smooth_predictions(scores: np.ndarray, threshold: float,
                       consecutive: int = CONSECUTIVE_ANOMALOUS_MINUTES) -> np.ndarray:
    """Anomalous only after `consecutive` minutes below threshold in a row —
    mirrors the streak logic used by the live inference tick."""
    below = scores < threshold
    out = np.zeros_like(below)
    run = 0
    for i, b in enumerate(below):
        run = run + 1 if b else 0
        out[i] = run >= consecutive
    return out


def save_model(model: AnomalyModel, observer_id: uuid.UUID | None) -> str:
    artifact_dir = Path(get_settings().ml_artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    path = artifact_dir / f"iforest_{observer_id or 'global'}_{stamp}.joblib"
    joblib.dump({"pipeline": model.pipeline, "threshold": model.threshold}, path)
    return str(path)


def load_model(artifact_path: str) -> AnomalyModel:
    blob = joblib.load(artifact_path)
    return AnomalyModel(pipeline=blob["pipeline"], threshold=blob["threshold"])
