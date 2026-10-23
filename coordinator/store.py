"""SQLite tabanlı görev deposu, durum geçişleri, zamanlayıcı entegrasyonu ve lease/kurtarma mantığı."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from models.predictor import TaskDurationPredictor
from scheduler.schedulers import BaseScheduler, WorkerView, create_scheduler
from tasks.runner import compute_base_duration_seconds, validate_task


class CoordinatorStore:
    """Görev yaşam döngüsünü, worker durumlarını ve olay kayıtlarını yönetir."""

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        scheduler_name: str = "ml_predictor",
        heartbeat_timeout_sec: float = 2.0,
        lease_duration_sec: float = 4.0,
    ) -> None:
        self.db_path = str(db_path)
        self.lock = threading.RLock()
        self.predictor = TaskDurationPredictor()
        self.scheduler: BaseScheduler = create_scheduler(scheduler_name, predictor=self.predictor)
        self.heartbeat_timeout_sec = float(heartbeat_timeout_sec)
        self.lease_duration_sec = float(lease_duration_sec)

        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self.lock, self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workers (
                    worker_id TEXT PRIMARY KEY,
                    speed_factor REAL NOT NULL,
                    cpu_load REAL NOT NULL DEFAULT 1.0,
                    status TEXT NOT NULL DEFAULT 'active',
                    last_heartbeat REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    input_size REAL NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 1,
                    assigned_worker TEXT,
                    predicted_seconds REAL NOT NULL DEFAULT 0.0,
                    estimated_work_seconds REAL NOT NULL DEFAULT 0.0,
                    lease_until REAL,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    actual_seconds REAL,
                    result TEXT,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS task_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    worker_id TEXT,
                    attempt INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    metadata TEXT
                );
                """
            )

    def set_scheduler(self, scheduler_name: str) -> str:
        with self.lock:
            self.predictor.load()
            self.scheduler = create_scheduler(scheduler_name, predictor=self.predictor)
            return self.scheduler.name

    def reset_tasks_and_events(self) -> None:
        with self.lock, self.conn:
            self.conn.execute("DELETE FROM tasks")
            self.conn.execute("DELETE FROM task_events")

    def _log_event(
        self,
        task_id: str,
        attempt: int,
        event_type: str,
        worker_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO task_events (task_id, worker_id, attempt, event_type, timestamp, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                worker_id,
                attempt,
                event_type,
                time.time(),
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )

    def register_worker(
        self,
        worker_id: str,
        speed_factor: float = 1.0,
        cpu_load: float = 1.0,
    ) -> Dict[str, Any]:
        now = time.time()
        with self.lock, self.conn:
            self.conn.execute(
                """
                INSERT INTO workers (worker_id, speed_factor, cpu_load, status, last_heartbeat)
                VALUES (?, ?, ?, 'active', ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                    speed_factor = excluded.speed_factor,
                    cpu_load = excluded.cpu_load,
                    status = 'active',
                    last_heartbeat = excluded.last_heartbeat
                """,
                (worker_id, float(speed_factor), float(cpu_load), now),
            )
        return {"worker_id": worker_id, "status": "active", "speed_factor": speed_factor}

    def heartbeat_worker(self, worker_id: str, cpu_load: float = 1.0) -> Dict[str, Any]:
        now = time.time()
        with self.lock, self.conn:
            cur = self.conn.execute(
                """
                UPDATE workers
                SET last_heartbeat = ?, cpu_load = ?, status = 'active'
                WHERE worker_id = ?
                """,
                (now, float(cpu_load), worker_id),
            )
            if cur.rowcount == 0:
                self.conn.execute(
                    """
                    INSERT INTO workers (worker_id, speed_factor, cpu_load, status, last_heartbeat)
                    VALUES (?, 1.0, ?, 'active', ?)
                    """,
                    (worker_id, float(cpu_load), now),
                )
        return {"ok": True, "timestamp": now}

    def _get_active_worker_views(self) -> List[WorkerView]:
        now = time.time()
        rows = self.conn.execute(
            "SELECT * FROM workers WHERE status = 'active' ORDER BY worker_id"
        ).fetchall()

        views: List[WorkerView] = []
        for w in rows:
            wid = w["worker_id"]
            t_rows = self.conn.execute(
                """
                SELECT status, estimated_work_seconds, started_at
                FROM tasks
                WHERE assigned_worker = ? AND status IN ('queued', 'running')
                """,
                (wid,),
            ).fetchall()

            queue_count = len(t_rows)
            rem_sec = 0.0
            for t in t_rows:
                est = float(t["estimated_work_seconds"])
                if t["status"] == "running" and t["started_at"]:
                    elapsed = max(0.0, now - float(t["started_at"]))
                    rem_sec += max(0.02, est - elapsed)
                else:
                    rem_sec += est

            views.append(
                WorkerView(
                    worker_id=wid,
                    speed_factor=float(w["speed_factor"]),
                    cpu_load=float(w["cpu_load"]),
                    queue_count=queue_count,
                    queue_remaining_seconds=rem_sec,
                )
            )
        return views

    def _estimate_work_seconds_for_worker(
        self,
        worker_id: str,
        task_type: str,
        input_size: float,
        predicted_sec: float,
    ) -> float:
        if predicted_sec > 0:
            return predicted_sec
        w = self.conn.execute(
            "SELECT speed_factor, cpu_load FROM workers WHERE worker_id = ?",
            (worker_id,),
        ).fetchone()
        speed = float(w["speed_factor"]) if w else 1.0
        load = float(w["cpu_load"]) if w else 1.0
        return self.predictor.predict_seconds(task_type, input_size, speed, load)

    def submit_task(
        self,
        task_type: str,
        input_size: float,
        payload: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        validate_task(task_type, float(input_size))
        tid = task_id or f"task-{uuid.uuid4().hex[:8]}"
        now = time.time()

        with self.lock, self.conn:
            views = self._get_active_worker_views()
            chosen_worker, pred_sec, meta = self.scheduler.select_worker(
                views, task_type=task_type, input_size=float(input_size)
            )
            est_sec = self._estimate_work_seconds_for_worker(
                chosen_worker, task_type, float(input_size), pred_sec
            )

            self.conn.execute(
                """
                INSERT INTO tasks (
                    task_id, task_type, input_size, payload, status,
                    attempt, assigned_worker, predicted_seconds, estimated_work_seconds,
                    created_at
                )
                VALUES (?, ?, ?, ?, 'queued', 1, ?, ?, ?, ?)
                """,
                (
                    tid,
                    task_type,
                    float(input_size),
                    json.dumps(payload or {}, ensure_ascii=False),
                    chosen_worker,
                    float(pred_sec),
                    float(est_sec),
                    now,
                ),
            )
            self._log_event(
                task_id=tid,
                attempt=1,
                event_type="queued_and_assigned",
                worker_id=chosen_worker,
                metadata=meta,
            )

            return {
                "task_id": tid,
                "status": "queued",
                "attempt": 1,
                "assigned_worker": chosen_worker,
                "predicted_seconds": pred_sec,
                "scheduler_meta": meta,
            }

    def poll_task_for_worker(self, worker_id: str) -> Optional[Dict[str, Any]]:
        now = time.time()
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE workers SET last_heartbeat = ?, status = 'active' WHERE worker_id = ?",
                (now, worker_id),
            )
            row = self.conn.execute(
                """
                SELECT * FROM tasks
                WHERE assigned_worker = ? AND status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (worker_id,),
            ).fetchone()

            if row is None:
                return None

            tid = row["task_id"]
            attempt = int(row["attempt"])
            est_sec = float(row["estimated_work_seconds"])
            lease_until = now + max(self.lease_duration_sec, est_sec * 2.5)

            self.conn.execute(
                """
                UPDATE tasks
                SET status = 'running', started_at = ?, lease_until = ?
                WHERE task_id = ? AND attempt = ?
                """,
                (now, lease_until, tid, attempt),
            )
            self._log_event(
                task_id=tid,
                attempt=attempt,
                event_type="running",
                worker_id=worker_id,
                metadata={"lease_until": round(lease_until, 3)},
            )

            return {
                "task_id": tid,
                "task_type": row["task_type"],
                "input_size": float(row["input_size"]),
                "payload": json.loads(row["payload"]),
                "attempt": attempt,
                "lease_until": lease_until,
            }

    def complete_task(
        self,
        task_id: str,
        worker_id: str,
        attempt: int,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = time.time()
        with self.lock, self.conn:
            row = self.conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                return {"accepted": False, "reason": "task_not_found"}

            current_attempt = int(row["attempt"])
            current_status = row["status"]

            # İdempotent sonuç ve eski lease/attempt kontrolü
            if attempt != current_attempt or current_status == "succeeded":
                self._log_event(
                    task_id=task_id,
                    attempt=attempt,
                    event_type="stale_attempt_rejected",
                    worker_id=worker_id,
                    metadata={
                        "current_attempt": current_attempt,
                        "current_status": current_status,
                    },
                )
                return {
                    "accepted": False,
                    "reason": "stale_attempt_or_already_completed",
                    "current_attempt": current_attempt,
                }

            started_at = float(row["started_at"] or now)
            actual_sec = max(0.001, now - started_at)
            new_status = "failed" if error else "succeeded"

            self.conn.execute(
                """
                UPDATE tasks
                SET status = ?, finished_at = ?, actual_seconds = ?, result = ?, error = ?
                WHERE task_id = ? AND attempt = ?
                """,
                (
                    new_status,
                    now,
                    actual_sec,
                    json.dumps(result or {}, ensure_ascii=False),
                    error,
                    task_id,
                    current_attempt,
                ),
            )
            self._log_event(
                task_id=task_id,
                attempt=current_attempt,
                event_type=new_status,
                worker_id=worker_id,
                metadata={"actual_seconds": round(actual_sec, 4)},
            )
            return {"accepted": True, "status": new_status, "actual_seconds": round(actual_sec, 4)}

    def check_timeouts_and_reassign(self) -> List[Dict[str, Any]]:
        """Heartbeat kesilen worker'ları veya lease süresi dolan görevleri tespit edip yeniden atar."""
        now = time.time()
        recovered: List[Dict[str, Any]] = []

        with self.lock, self.conn:
            dead_workers = self.conn.execute(
                """
                SELECT worker_id, last_heartbeat FROM workers
                WHERE status = 'active' AND (? - last_heartbeat) > ?
                """,
                (now, self.heartbeat_timeout_sec),
            ).fetchall()

            dead_ids = [w["worker_id"] for w in dead_workers]
            for wid in dead_ids:
                self.conn.execute(
                    "UPDATE workers SET status = 'unavailable' WHERE worker_id = ?",
                    (wid,),
                )

            # Ölen worker üzerindeki queued/running görevler veya lease süresi dolan running görevler
            orphaned_tasks = self.conn.execute(
                """
                SELECT * FROM tasks
                WHERE (status IN ('queued', 'running') AND assigned_worker IN (
                    SELECT worker_id FROM workers WHERE status = 'unavailable'
                ))
                OR (status = 'running' AND lease_until IS NOT NULL AND lease_until < ?)
                ORDER BY created_at ASC
                """,
                (now,),
            ).fetchall()

            if not orphaned_tasks:
                return recovered

            active_views = self._get_active_worker_views()
            if not active_views:
                return recovered

            for task in orphaned_tasks:
                tid = task["task_id"]
                old_worker = task["assigned_worker"]
                old_attempt = int(task["attempt"])
                new_attempt = old_attempt + 1
                t_type = task["task_type"]
                in_size = float(task["input_size"])

                active_views = self._get_active_worker_views()
                new_worker, pred_sec, meta = self.scheduler.select_worker(
                    active_views, task_type=t_type, input_size=in_size
                )
                est_sec = self._estimate_work_seconds_for_worker(
                    new_worker, t_type, in_size, pred_sec
                )

                self.conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'queued',
                        attempt = ?,
                        assigned_worker = ?,
                        predicted_seconds = ?,
                        estimated_work_seconds = ?,
                        started_at = NULL,
                        lease_until = NULL
                    WHERE task_id = ?
                    """,
                    (new_attempt, new_worker, float(pred_sec), float(est_sec), tid),
                )

                recovery_info = {
                    "task_id": tid,
                    "failed_worker": old_worker,
                    "new_worker": new_worker,
                    "old_attempt": old_attempt,
                    "new_attempt": new_attempt,
                    "recovery_timestamp": now,
                }
                self._log_event(
                    task_id=tid,
                    attempt=new_attempt,
                    event_type="reassigned_after_failure",
                    worker_id=new_worker,
                    metadata=recovery_info,
                )
                recovered.append(recovery_info)

        return recovered

    def get_summary(self) -> Dict[str, Any]:
        with self.lock:
            workers = [
                dict(row)
                for row in self.conn.execute("SELECT * FROM workers ORDER BY worker_id").fetchall()
            ]
            tasks = [
                dict(row)
                for row in self.conn.execute("SELECT * FROM tasks ORDER BY created_at ASC").fetchall()
            ]
            events = [
                dict(row)
                for row in self.conn.execute(
                    "SELECT * FROM task_events ORDER BY event_id ASC"
                ).fetchall()
            ]

            counts: Dict[str, int] = {"queued": 0, "running": 0, "succeeded": 0, "failed": 0}
            for t in tasks:
                counts[t["status"]] = counts.get(t["status"], 0) + 1

            return {
                "scheduler": self.scheduler.name,
                "counts": counts,
                "total_tasks": len(tasks),
                "workers": workers,
                "tasks": tasks,
                "events": events,
            }
