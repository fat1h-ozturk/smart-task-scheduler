"""Kalibrasyon verisi üretimi ve görev süresi tahmin modelinin eğitilmesi."""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Dict, List

from models.predictor import DEFAULT_MODEL_PATH, train_and_evaluate
from tasks.runner import SUPPORTED_TASK_TYPES, compute_base_duration_seconds


def generate_calibration_dataset(seed: int = 42, num_samples: int = 90) -> List[Dict[str, Any]]:
    """Heterojen worker profilleri üzerinde geçmiş çalıştırma kayıtlarını simüle eder."""
    rng = random.Random(seed)
    worker_speeds = [1.0, 0.5, 0.25]
    records: List[Dict[str, Any]] = []

    for _ in range(num_samples):
        task_type = rng.choice(SUPPORTED_TASK_TYPES)
        input_size = rng.choice([1.0, 2.0, 3.5, 5.0, 7.0, 9.0])
        worker_speed = rng.choice(worker_speeds)
        cpu_load = round(rng.uniform(1.0, 1.12), 3)

        base_sec = compute_base_duration_seconds(task_type, input_size)
        # Küçük gerçekçi sistem/ağ gürültüsü (%2-%5)
        noise = rng.uniform(0.98, 1.04)
        actual_duration = (base_sec / worker_speed) * cpu_load * noise

        records.append(
            {
                "task_type": task_type,
                "input_size": input_size,
                "worker_speed": worker_speed,
                "cpu_load": cpu_load,
                "actual_duration": round(actual_duration, 4),
            }
        )
    return records


def main() -> None:
    records = generate_calibration_dataset()
    result = train_and_evaluate(records, save_path=DEFAULT_MODEL_PATH)
    print("=== ML Görev Süresi Tahmin Modeli Eğitildi ===")
    print(f"Model dosyası : {DEFAULT_MODEL_PATH}")
    print(f"Eğitim örneği : {result['train_samples']}")
    print(f"Test örneği   : {result['test_samples']}")
    print(f"Test MAE (sn) : {result['metrics']['mae_seconds']:.4f}")
    print(f"Test RMSE (sn): {result['metrics']['rmse_seconds']:.4f}")


if __name__ == "__main__":
    main()
