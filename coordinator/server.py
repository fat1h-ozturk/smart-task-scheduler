"""Koordinatör HTTP JSON API Sunucusu ve Arka Plan Arıza İzleyicisi."""

from __future__ import annotations

import argparse
import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict

from coordinator.store import CoordinatorStore


class CoordinatorHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], store: CoordinatorStore) -> None:
        super().__init__(server_address, CoordinatorRequestHandler)
        self.store = store


class CoordinatorRequestHandler(BaseHTTPRequestHandler):
    server: CoordinatorHTTPServer

    def log_message(self, format: str, *args: Any) -> None:
        # Konsol çıktısını temiz tutmak için varsayılan HTTP erişim loglarını sustur
        pass

    def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body) if body else {}

    def do_GET(self) -> None:
        if self.path == "/status":
            self._send_json(HTTPStatus.OK, self.server.store.get_summary())
            return
        if self.path == "/health":
            self._send_json(HTTPStatus.OK, {"ok": True})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self) -> None:
        try:
            body = self._read_json()
            store = self.server.store

            if self.path == "/workers/register":
                res = store.register_worker(
                    worker_id=str(body["worker_id"]),
                    speed_factor=float(body.get("speed_factor", 1.0)),
                    cpu_load=float(body.get("cpu_load", 1.0)),
                )
                self._send_json(HTTPStatus.OK, res)
                return

            if self.path == "/workers/heartbeat":
                res = store.heartbeat_worker(
                    worker_id=str(body["worker_id"]),
                    cpu_load=float(body.get("cpu_load", 1.0)),
                )
                self._send_json(HTTPStatus.OK, res)
                return

            if self.path == "/workers/poll":
                task = store.poll_task_for_worker(worker_id=str(body["worker_id"]))
                self._send_json(HTTPStatus.OK, {"task": task})
                return

            if self.path == "/tasks":
                res = store.submit_task(
                    task_type=str(body["task_type"]),
                    input_size=float(body["input_size"]),
                    payload=body.get("payload"),
                    task_id=body.get("task_id"),
                )
                self._send_json(HTTPStatus.CREATED, res)
                return

            if self.path == "/tasks/complete":
                res = store.complete_task(
                    task_id=str(body["task_id"]),
                    worker_id=str(body["worker_id"]),
                    attempt=int(body["attempt"]),
                    result=body.get("result"),
                    error=body.get("error"),
                )
                self._send_json(HTTPStatus.OK, res)
                return

            if self.path == "/admin/scheduler":
                name = store.set_scheduler(str(body["scheduler"]))
                self._send_json(HTTPStatus.OK, {"scheduler": name})
                return

            if self.path == "/admin/reset":
                store.reset_tasks_and_events()
                self._send_json(HTTPStatus.OK, {"ok": True})
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})


def start_fault_monitor(
    store: CoordinatorStore,
    stop_event: threading.Event,
    interval_sec: float = 0.2,
    verbose: bool = True,
) -> threading.Thread:
    def _loop() -> None:
        while not stop_event.is_set():
            recovered = store.check_timeouts_and_reassign()
            if verbose:
                for item in recovered:
                    print(
                        f"[KOORDİNATÖR KURTARMA] Görev {item['task_id']} | "
                        f"Yanıt vermeyen: {item['failed_worker']} -> "
                        f"Yeni worker: {item['new_worker']} (Deneme {item['old_attempt']} -> {item['new_attempt']})"
                    )
            stop_event.wait(interval_sec)

    thread = threading.Thread(target=_loop, name="fault-monitor", daemon=True)
    thread.start()
    return thread


def main() -> None:
    parser = argparse.ArgumentParser(description="Dağıtık Görev Koordinatörü")
    parser.add_argument("--host", default="127.0.0.1", help="Sunucu adresi")
    parser.add_argument("--port", type=int, default=8000, help="Sunucu portu")
    parser.add_argument("--db", default="coordinator.db", help="SQLite veritabanı yolu")
    parser.add_argument(
        "--scheduler",
        default="ml_predictor",
        choices=["round_robin", "shortest_queue", "ml_predictor"],
        help="Başlangıç zamanlayıcı algoritması",
    )
    parser.add_argument(
        "--heartbeat-timeout",
        type=float,
        default=1.5,
        help="Worker heartbeat zaman aşımı (saniye)",
    )
    args = parser.parse_args()

    store = CoordinatorStore(
        db_path=args.db,
        scheduler_name=args.scheduler,
        heartbeat_timeout_sec=args.heartbeat_timeout,
    )
    stop_event = threading.Event()
    start_fault_monitor(store, stop_event=stop_event, verbose=True)

    server = CoordinatorHTTPServer((args.host, args.port), store)
    print(
        f"[KOORDİNATÖR] http://{args.host}:{args.port} üzerinde çalışıyor "
        f"(Zamanlayıcı: {args.scheduler}, DB: {args.db})"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[KOORDİNATÖR] Kapatılıyor...")
    finally:
        stop_event.set()
        server.server_close()


if __name__ == "__main__":
    main()
