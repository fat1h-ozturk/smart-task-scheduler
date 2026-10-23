"""Üç zamanlayıcı (scheduler) yönteminin ortak arayüzü ve uygulamaları.

1. RoundRobinScheduler   : Uygun worker'lar arasında sırayla dağıtım yapar.
2. ShortestQueueScheduler: Kuyruğunda en az bekleyen/çalışan görev (adet) olan worker'ı seçer.
3. MLPredictorScheduler  : score(w, t) = worker_queue_remaining_seconds + predicted_task_seconds
                           hesabıyla görevi en erken bitirecek worker'ı seçer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from models.predictor import TaskDurationPredictor


@dataclass
class WorkerView:
    worker_id: str
    speed_factor: float
    cpu_load: float
    queue_count: int
    queue_remaining_seconds: float


class BaseScheduler:
    name: str = "base"

    def select_worker(
        self,
        workers: List[WorkerView],
        task_type: str,
        input_size: float,
    ) -> Tuple[str, float, Dict[str, Any]]:
        """Uygun bir worker seçer ve (worker_id, predicted_seconds, debug_meta) döndürür."""
        raise NotImplementedError


class RoundRobinScheduler(BaseScheduler):
    name = "round_robin"

    def __init__(self) -> None:
        self._cursor = 0

    def select_worker(
        self,
        workers: List[WorkerView],
        task_type: str,
        input_size: float,
    ) -> Tuple[str, float, Dict[str, Any]]:
        if not workers:
            raise RuntimeError("Atama yapılacak aktif worker bulunamadı.")
        ordered = sorted(workers, key=lambda w: w.worker_id)
        chosen = ordered[self._cursor % len(ordered)]
        self._cursor += 1
        return chosen.worker_id, 0.0, {"strategy": "round_robin", "queue_count": chosen.queue_count}


class ShortestQueueScheduler(BaseScheduler):
    name = "shortest_queue"

    def select_worker(
        self,
        workers: List[WorkerView],
        task_type: str,
        input_size: float,
    ) -> Tuple[str, float, Dict[str, Any]]:
        if not workers:
            raise RuntimeError("Atama yapılacak aktif worker bulunamadı.")
        # Görev adedine (queue_count) göre en kısa kuyruğu seç; eşitlikte worker_id ile kır
        chosen = min(workers, key=lambda w: (w.queue_count, w.worker_id))
        return chosen.worker_id, 0.0, {
            "strategy": "shortest_queue_count",
            "queue_count": chosen.queue_count,
        }


class MLPredictorScheduler(BaseScheduler):
    name = "ml_predictor"

    def __init__(self, predictor: TaskDurationPredictor | None = None) -> None:
        self.predictor = predictor or TaskDurationPredictor()

    def select_worker(
        self,
        workers: List[WorkerView],
        task_type: str,
        input_size: float,
    ) -> Tuple[str, float, Dict[str, Any]]:
        if not workers:
            raise RuntimeError("Atama yapılacak aktif worker bulunamadı.")

        best_worker: WorkerView | None = None
        best_score = float("inf")
        best_pred = 0.0
        candidate_scores: Dict[str, float] = {}

        for w in sorted(workers, key=lambda item: item.worker_id):
            pred_sec = self.predictor.predict_seconds(
                task_type=task_type,
                input_size=input_size,
                worker_speed=w.speed_factor,
                cpu_load=w.cpu_load,
            )
            score = w.queue_remaining_seconds + pred_sec
            candidate_scores[w.worker_id] = round(score, 3)
            if score < best_score:
                best_score = score
                best_worker = w
                best_pred = pred_sec

        assert best_worker is not None
        return best_worker.worker_id, round(best_pred, 4), {
            "strategy": "ml_predictor",
            "predicted_seconds": round(best_pred, 4),
            "estimated_completion_score": round(best_score, 4),
            "candidate_scores": candidate_scores,
        }


def create_scheduler(name: str, predictor: TaskDurationPredictor | None = None) -> BaseScheduler:
    normalized = name.strip().lower()
    if normalized in ("round_robin", "rr"):
        return RoundRobinScheduler()
    if normalized in ("shortest_queue", "sq"):
        return ShortestQueueScheduler()
    if normalized in ("ml_predictor", "ml"):
        return MLPredictorScheduler(predictor=predictor)
    raise ValueError(f"Bilinmeyen zamanlayıcı: '{name}'. Seçenekler: round_robin, shortest_queue, ml_predictor")
