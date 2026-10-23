"""Worker (Çalışan) Ajanı.

Koordinatöre kaydolur, düzenli heartbeat gönderir, kendisine atanan görevleri sırayla
çekip hız çarpanına (speed_factor) göre çalıştırır ve sonucu bildirir.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from tasks.runner import execute_task


def _post_json(url: str, payload: Dict[str, Any], timeout: float = 3.0) -> Dict[str, Any]:
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class WorkerAgent:
    def __init__(
        self,
        worker_id: str,
        coordinator_url: str = "http://127.0.0.1:8000",
        speed_factor: float = 1.0,
        heartbeat_interval: float = 0.4,
        poll_interval: float = 0.08,
        verbose: bool = True,
    ) -> None:
        self.worker_id = worker_id
        self.coordinator_url = coordinator_url.rstrip("/")
        self.speed_factor = float(speed_factor)
        self.heartbeat_interval = float(heartbeat_interval)
        self.poll_interval = float(poll_interval)
        self.verbose = verbose
        self.stop_event = threading.Event()
        self.current_cpu_load = 1.0
        self._hb_thread: Optional[threading.Thread] = None

    def register(self) -> None:
        _post_json(
            f"{self.coordinator_url}/workers/register",
            {
                "worker_id": self.worker_id,
                "speed_factor": self.speed_factor,
                "cpu_load": self.current_cpu_load,
            },
        )
        if self.verbose:
            print(f"[{self.worker_id}] Koordinatöre kaydoldu (hız çarpanı: {self.speed_factor}x)")

    def _heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                _post_json(
                    f"{self.coordinator_url}/workers/heartbeat",
                    {"worker_id": self.worker_id, "cpu_load": self.current_cpu_load},
                )
            except Exception:
                pass
            self.stop_event.wait(self.heartbeat_interval)

    def start_background(self) -> threading.Thread:
        self.register()
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop, name=f"hb-{self.worker_id}", daemon=True
        )
        self._hb_thread.start()
        work_thread = threading.Thread(
            target=self.run_loop, name=f"work-{self.worker_id}", daemon=True
        )
        work_thread.start()
        return work_thread

    def stop(self) -> None:
        self.stop_event.set()

    def run_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                resp = _post_json(
                    f"{self.coordinator_url}/workers/poll",
                    {"worker_id": self.worker_id},
                )
                task = resp.get("task")
            except Exception:
                self.stop_event.wait(self.poll_interval)
                continue

            if not task:
                self.stop_event.wait(self.poll_interval)
                continue

            tid = task["task_id"]
            t_type = task["task_type"]
            in_size = float(task["input_size"])
            attempt = int(task["attempt"])

            if self.verbose:
                print(
                    f"[{self.worker_id}] Başladı -> {tid} ({t_type}, boyut={in_size}, deneme={attempt})"
                )

            try:
                self.current_cpu_load = 1.05
                result = execute_task(
                    task_id=tid,
                    task_type=t_type,
                    input_size=in_size,
                    payload=task.get("payload"),
                    worker_speed=self.speed_factor,
                )
                self.current_cpu_load = 1.0
                if self.stop_event.is_set():
                    break
                comp = _post_json(
                    f"{self.coordinator_url}/tasks/complete",
                    {
                        "task_id": tid,
                        "worker_id": self.worker_id,
                        "attempt": attempt,
                        "result": result,
                    },
                )
                if self.verbose:
                    status_str = "TAMAMLANDI" if comp.get("accepted") else "REDDEDİLDİ (ESKİ DENEME)"
                    print(
                        f"[{self.worker_id}] {status_str} -> {tid} "
                        f"({result['actual_worker_seconds']:.2f} sn)"
                    )
            except Exception as exc:
                self.current_cpu_load = 1.0
                if not self.stop_event.is_set():
                    try:
                        _post_json(
                            f"{self.coordinator_url}/tasks/complete",
                            {
                                "task_id": tid,
                                "worker_id": self.worker_id,
                                "attempt": attempt,
                                "error": str(exc),
                            },
                        )
                    except Exception:
                        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Dağıtık Görev Worker Süreci")
    parser.add_argument("--id", required=True, help="Worker kimliği (ör. worker-A)")
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Worker hız çarpanı (1.0=hızlı, 0.5=orta, 0.25=yavaş)",
    )
    parser.add_argument(
        "--coordinator",
        default="http://127.0.0.1:8000",
        help="Koordinatör HTTP adresi",
    )
    args = parser.parse_args()

    agent = WorkerAgent(
        worker_id=args.id,
        coordinator_url=args.coordinator,
        speed_factor=args.speed,
        verbose=True,
    )
    agent.register()
    hb = threading.Thread(target=agent._heartbeat_loop, daemon=True)
    hb.start()
    try:
        agent.run_loop()
    except KeyboardInterrupt:
        print(f"\n[{args.id}] Durduruldu.")
    finally:
        agent.stop()


if __name__ == "__main__":
    main()
