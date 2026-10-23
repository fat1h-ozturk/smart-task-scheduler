"""Uçtan Uca Karşılaştırma ve Arıza Toleransı Demo Sürücüsü.

Bu betik tek komutla:
1. ML görev süresi tahmin modelini eğitir ve test MAE/RMSE değerlerini raporlar.
2. Koordinatörü ve 3 heterojen worker'ı (Hızlı=1.0x, Orta=0.45x, Yavaş=0.20x) başlatır.
3. Aynı sabit iş yükünü (küçük/orta/büyük görevler) sırasıyla:
   - Round-Robin
   - En Kısa Kuyruk (Shortest Queue)
   - ML Tahminli Zamanlayıcı (ML Predictor)
   ile çalıştırıp Makespan, Ortalama Bekleme ve P95 Bekleme sürelerini ölçer.
4. Kontrollü Worker Arızası (Fault Tolerance) deneyini çalıştırır:
   - Görevler çalışırken worker-B'yi kapatır,
   - Koordinatörün heartbeat/lease zaman aşımıyla görevleri başka worker'a devrettiğini,
   - Eski worker'dan gecikmeli gelen (eski attempt numaralı) sonucun reddedildiğini gösterir.
"""

from __future__ import annotations

import json
import math
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from coordinator.server import CoordinatorHTTPServer, start_fault_monitor
from coordinator.store import CoordinatorStore
from models.predictor import DEFAULT_MODEL_PATH
from models.train import generate_calibration_dataset, train_and_evaluate
from worker.agent import WorkerAgent, _post_json

RESULTS_PATH = Path(__file__).resolve().parent / "latest_results.json"


def build_standard_workload() -> List[Dict[str, Any]]:
    """Farklı boyutlarda deterministik görev listesi (12 görev).

    Küçük ve büyük işlerin karışık gelmesi, heterojen worker havuzunda
    süre tahmini yapmanın etkisini net biçimde ortaya çıkarır.
    """
    specs = [
        ("t01", "matrix_compute", 3.2),
        ("t02", "image_resize", 1.0),
        ("t03", "matrix_compute", 3.5),
        ("t04", "image_resize", 1.2),
        ("t05", "image_resize", 1.0),
        ("t06", "matrix_compute", 3.0),
        ("t07", "image_resize", 4.0),
        ("t08", "image_resize", 1.0),
        ("t09", "matrix_compute", 2.8),
        ("t10", "image_resize", 1.5),
        ("t11", "image_resize", 3.8),
        ("t12", "matrix_compute", 2.5),
    ]
    return [
        {"task_id": tid, "task_type": t_type, "input_size": size, "payload": {"seq": idx + 1}}
        for idx, (tid, t_type, size) in enumerate(specs)
    ]


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil((p / 100.0) * len(ordered)) - 1))
    return float(ordered[idx])


def get_status(base_url: str) -> Dict[str, Any]:
    with urllib.request.urlopen(f"{base_url}/status", timeout=3.0) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_scheduler_experiment(
    base_url: str,
    scheduler_name: str,
    workload: List[Dict[str, Any]],
    arrival_gap_sec: float = 0.04,
) -> Dict[str, Any]:
    _post_json(f"{base_url}/admin/reset", {})
    _post_json(f"{base_url}/admin/scheduler", {"scheduler": scheduler_name})

    start_wall = time.time()
    for item in workload:
        _post_json(f"{base_url}/tasks", item)
        time.sleep(arrival_gap_sec)

    # Tüm görevler tamamlanana kadar bekle
    while True:
        summary = get_status(base_url)
        if summary["counts"].get("succeeded", 0) == len(workload):
            break
        time.sleep(0.05)

    end_wall = time.time()
    summary = get_status(base_url)
    tasks = summary["tasks"]

    created_times = [float(t["created_at"]) for t in tasks]
    finished_times = [float(t["finished_at"]) for t in tasks if t["finished_at"]]
    makespan = max(finished_times) - min(created_times) if finished_times else (end_wall - start_wall)

    wait_times = [
        max(0.0, float(t["started_at"]) - float(t["created_at"]))
        for t in tasks
        if t["started_at"] and t["created_at"]
    ]
    pred_errors = [
        abs(float(t["actual_seconds"]) - float(t["predicted_seconds"]))
        for t in tasks
        if float(t["predicted_seconds"]) > 0 and t["actual_seconds"]
    ]

    worker_dist: Dict[str, int] = {}
    for t in tasks:
        wid = t["assigned_worker"]
        worker_dist[wid] = worker_dist.get(wid, 0) + 1

    return {
        "scheduler": scheduler_name,
        "makespan_sec": round(makespan, 3),
        "avg_wait_sec": round(sum(wait_times) / len(wait_times), 3) if wait_times else 0.0,
        "p95_wait_sec": round(percentile(wait_times, 95), 3),
        "runtime_mae_sec": round(sum(pred_errors) / len(pred_errors), 4) if pred_errors else None,
        "worker_distribution": worker_dist,
    }


def run_fault_tolerance_demo(
    base_url: str,
    workers: Dict[str, WorkerAgent],
) -> Dict[str, Any]:
    print("\n--- [DENEY 2] Worker Arızası ve Otomatik Görev Kurtarma Senaryosu ---")
    _post_json(f"{base_url}/admin/reset", {})
    _post_json(f"{base_url}/admin/scheduler", {"scheduler": "round_robin"})

    fault_workload = [
        {"task_id": "fault-1", "task_type": "image_resize", "input_size": 2.0},
        {"task_id": "fault-2", "task_type": "matrix_compute", "input_size": 3.0},
        {"task_id": "fault-3", "task_type": "image_resize", "input_size": 2.0},
        {"task_id": "fault-4", "task_type": "image_resize", "input_size": 2.5},
        {"task_id": "fault-5", "task_type": "matrix_compute", "input_size": 2.5},
        {"task_id": "fault-6", "task_type": "image_resize", "input_size": 2.0},
    ]

    for item in fault_workload:
        _post_json(f"{base_url}/tasks", item)

    # worker-B bir görevi çalışmaya başladığı anda worker-B'yi zorla durdur!
    killed_at = None
    killed_task_id = None
    while True:
        summary = get_status(base_url)
        running_on_b = [
            t
            for t in summary["tasks"]
            if t["assigned_worker"] == "worker-B" and t["status"] == "running"
        ]
        if running_on_b:
            killed_task_id = running_on_b[0]["task_id"]
            print(
                f"[ARIZA ENJEKSİYONU] worker-B '{killed_task_id}' görevini yürütürken "
                f"durduruluyor (crash simülasyonu)..."
            )
            workers["worker-B"].stop()
            killed_at = time.time()
            break
        time.sleep(0.03)

    # Tüm 6 görevin kalan sağlam worker'larda tamamlanmasını bekle
    while True:
        summary = get_status(base_url)
        if summary["counts"].get("succeeded", 0) == len(fault_workload):
            break
        time.sleep(0.05)

    # Eski (ölen) worker-B'nin gecikmeli olarak eski deneme (attempt=1) sonucu göndermesini test et
    stale_response = _post_json(
        f"{base_url}/tasks/complete",
        {
            "task_id": killed_task_id or "fault-2",
            "worker_id": "worker-B",
            "attempt": 1,
            "result": {"checksum": "stale_invalid"},
        },
    )
    print(
        f"[İDEMPOTENT KORUMA TESTİ] Eski worker-B'den gelen gecikmeli sonuç (attempt=1) -> "
        f"Kabul edildi mi?: {stale_response.get('accepted')} "
        f"(Sebep: {stale_response.get('reason')})"
    )

    summary = get_status(base_url)
    recovery_events = [
        ev for ev in summary["events"] if ev["event_type"] == "reassigned_after_failure"
    ]
    recovery_delay_sec = 0.0
    if recovery_events and killed_at:
        first_rec = float(recovery_events[0]["timestamp"])
        recovery_delay_sec = max(0.0, first_rec - killed_at)

    return {
        "total_tasks": len(fault_workload),
        "succeeded_tasks": summary["counts"].get("succeeded", 0),
        "killed_worker": "worker-B",
        "reassigned_task_count": len(recovery_events),
        "recovery_time_sec": round(recovery_delay_sec, 3),
        "stale_result_rejected": not bool(stale_response.get("accepted", True)),
    }


def main() -> None:
    print("======================================================================")
    print("  ML DESTEKLİ, ARIZALARA DAYANIKLI DAĞITIK GÖREV ZAMANLAMA SİSTEMİ")
    print("======================================================================\n")

    # 1. Model eğitimi
    calib_records = generate_calibration_dataset(seed=42, num_samples=96)
    model_info = train_and_evaluate(calib_records, save_path=DEFAULT_MODEL_PATH)
    print(
        f"[1/3] ML Modeli Eğitildi ({model_info['train_samples']} eğitim, "
        f"{model_info['test_samples']} test kaydı) -> "
        f"Test MAE: {model_info['metrics']['mae_seconds']:.4f} sn | "
        f"Test RMSE: {model_info['metrics']['rmse_seconds']:.4f} sn"
    )

    # 2. Koordinatör ve 3 heterojen worker başlatma
    port = 8765
    base_url = f"http://127.0.0.1:{port}"
    store = CoordinatorStore(
        db_path=":memory:",
        scheduler_name="round_robin",
        heartbeat_timeout_sec=0.9,
        lease_duration_sec=2.0,
    )
    stop_monitor = threading.Event()
    start_fault_monitor(store, stop_event=stop_monitor, interval_sec=0.1, verbose=True)

    server = CoordinatorHTTPServer(("127.0.0.1", port), store)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    worker_Configs = [
        ("worker-A", 1.00),  # Hızlı bilgisayar
        ("worker-B", 0.45),  # Orta hızda bilgisayar
        ("worker-C", 0.20),  # Yavaş bilgisayar
    ]
    workers: Dict[str, WorkerAgent] = {}
    for wid, speed in worker_Configs:
        agent = WorkerAgent(
            worker_id=wid,
            coordinator_url=base_url,
            speed_factor=speed,
            heartbeat_interval=0.25,
            poll_interval=0.03,
            verbose=False,
        )
        agent.start_background()
        workers[wid] = agent

    print(
        "[2/3] Koordinatör ve 3 Heterojen Worker Başlatıldı: "
        "worker-A (1.0x Hızlı), worker-B (0.45x Orta), worker-C (0.20x Yavaş)\n"
    )

    workload = build_standard_workload()
    scheduler_results: List[Dict[str, Any]] = []

    print("--- [DENEY 1] Aynı İş Yükünde (12 Görev) 3 Zamanlayıcının Karşılaştırılması ---")
    for sched in ("round_robin", "shortest_queue", "ml_predictor"):
        print(f"  -> '{sched}' çalıştırılıyor...")
        res = run_scheduler_experiment(base_url, sched, workload)
        scheduler_results.append(res)

    print("\nSONUÇ TABLOSU (Heterojen Worker Havuzu, Arızasız Koşul):")
    print(
        f"{'Zamanlayıcı':<18} | {'Makespan (sn)':>14} | {'Ort. Bekleme (sn)':>17} | "
        f"{'P95 Bekleme (sn)':>16} | {'Görev Dağılımı (A / B / C)'}"
    )
    print("-" * 96)
    for r in scheduler_results:
        dist = r["worker_distribution"]
        dist_str = f"A:{dist.get('worker-A', 0)}  B:{dist.get('worker-B', 0)}  C:{dist.get('worker-C', 0)}"
        print(
            f"{r['scheduler']:<18} | {r['makespan_sec']:>14.3f} | {r['avg_wait_sec']:>17.3f} | "
            f"{r['p95_wait_sec']:>16.3f} | {dist_str}"
        )

    # 3. Arıza deneyi
    fault_result = run_fault_tolerance_demo(base_url, workers)
    print("\nARIZA DENEYİ ÖZETİ:")
    print(f"  - Toplam Görev / Tamamlanan : {fault_result['total_tasks']} / {fault_result['succeeded_tasks']}")
    print(f"  - Devre Dışı Kalan Worker   : {fault_result['killed_worker']}")
    print(f"  - Yeniden Atanan Görev Adedi: {fault_result['reassigned_task_count']}")
    print(f"  - Arıza Kurtarma Süresi     : {fault_result['recovery_time_sec']:.3f} sn")
    print(f"  - Mükerrer Sonuç Engellendi : {'EVET' if fault_result['stale_result_rejected'] else 'HAYIR'}")

    full_report = {
        "model_metrics": model_info["metrics"],
        "scheduler_comparison": scheduler_results,
        "fault_tolerance_experiment": fault_result,
    }
    RESULTS_PATH.write_text(json.dumps(full_report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[3/3] Tüm deney sonuçları kaydedildi: {RESULTS_PATH}")

    for w in workers.values():
        w.stop()
    stop_monitor.set()
    server.shutdown()
    server.server_close()


if __name__ == "__main__":
    main()
