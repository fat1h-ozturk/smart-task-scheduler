"""Görev süresi tahmin modeli (Regresyon + Soğuk Başlangıç Yedeği).

Atama anında bilinen özellikler:
- task_type ("image_resize" | "matrix_compute")
- input_size (sayısal görev büyüklüğü)
- worker_speed (worker kapasite/hız katsayısı)
- cpu_load (atama anındaki anlık yük katsayısı)
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "trained_model.json"


def extract_features(
    task_type: str,
    input_size: float,
    worker_speed: float,
    cpu_load: float = 1.0,
) -> List[float]:
    """Atama anında bilinen özelliklerden doğrusal olmayan özellik vektörü çıkarır."""
    is_image = 1.0 if task_type == "image_resize" else 0.0
    is_matrix = 1.0 if task_type == "matrix_compute" else 0.0
    inv_speed = 1.0 / max(0.05, float(worker_speed))
    size = float(input_size)
    size_nonlin = size ** 1.25
    load = max(1.0, float(cpu_load))

    return [
        1.0,  # bias
        is_image * inv_speed,
        is_matrix * inv_speed,
        is_image * size * inv_speed * load,
        is_matrix * size * inv_speed * load,
        is_matrix * size_nonlin * inv_speed * load,
    ]


class TaskDurationPredictor:
    """Eğitilmiş model ağırlıklarıyla görev süresini (saniye) tahmin eder."""

    def __init__(self, model_path: Path | str | None = None) -> None:
        self.model_path = Path(model_path) if model_path else DEFAULT_MODEL_PATH
        self.weights: List[float] | None = None
        self.metrics: Dict[str, float] = {}
        self.load()

    def load(self) -> bool:
        if self.model_path.exists():
            data = json.loads(self.model_path.read_text(encoding="utf-8"))
            self.weights = data.get("weights")
            self.metrics = data.get("metrics", {})
            return self.weights is not None
        return False

    def predict_seconds(
        self,
        task_type: str,
        input_size: float,
        worker_speed: float,
        cpu_load: float = 1.0,
    ) -> float:
        """Görevin ilgili worker üzerinde kaç saniye süreceğini tahmin eder."""
        if self.weights is not None:
            feats = np.asarray(
                extract_features(task_type, input_size, worker_speed, cpu_load),
                dtype=float,
            )
            w = np.asarray(self.weights, dtype=float)
            pred = float(np.dot(feats, w))
            return max(0.02, pred)

        # Soğuk başlangıç (Cold-start) basit tahmin yedeği
        inv_speed = 1.0 / max(0.1, float(worker_speed))
        return max(0.05, (0.1 + 0.1 * float(input_size)) * inv_speed)


def train_and_evaluate(
    records: List[Dict[str, Any]],
    save_path: Path | str | None = None,
    test_ratio: float = 0.25,
) -> Dict[str, Any]:
    """Geçmiş görev kayıtlarından modeli eğitir ve ayrılmış test kümesinde MAE/RMSE ölçer."""
    if len(records) < 8:
        raise ValueError("Eğitim için en az 8 tamamlanmış görev kaydı gereklidir.")

    # Zaman/koşu sırasını koruyarak eğitim ve test kümelerini ayır (veri sızıntısını önler)
    split_idx = max(4, int(len(records) * (1.0 - test_ratio)))
    train_records = records[:split_idx]
    test_records = records[split_idx:]

    X_train = np.asarray(
        [
            extract_features(
                r["task_type"],
                r["input_size"],
                r["worker_speed"],
                r.get("cpu_load", 1.0),
            )
            for r in train_records
        ],
        dtype=float,
    )
    y_train = np.asarray([float(r["actual_duration"]) for r in train_records], dtype=float)

    # Ridge / En küçük kareler çözümü (küçük L2 düzenlileştirme ile kararlı tahmin)
    reg = 1e-4 * np.eye(X_train.shape[1])
    weights = np.linalg.solve(X_train.T @ X_train + reg, X_train.T @ y_train)

    X_test = np.asarray(
        [
            extract_features(
                r["task_type"],
                r["input_size"],
                r["worker_speed"],
                r.get("cpu_load", 1.0),
            )
            for r in test_records
        ],
        dtype=float,
    )
    y_test = np.asarray([float(r["actual_duration"]) for r in test_records], dtype=float)
    y_pred = np.maximum(0.02, X_test @ weights)

    errors = np.abs(y_test - y_pred)
    mae = float(np.mean(errors))
    rmse = float(math.sqrt(float(np.mean((y_test - y_pred) ** 2))))

    payload = {
        "model_type": "RidgePolynomialRegressor",
        "train_samples": len(train_records),
        "test_samples": len(test_records),
        "weights": [round(float(x), 6) for x in weights],
        "metrics": {
            "mae_seconds": round(mae, 4),
            "rmse_seconds": round(rmse, 4),
        },
    }

    target_path = Path(save_path) if save_path else DEFAULT_MODEL_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload
