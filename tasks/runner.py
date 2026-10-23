"""Deterministik görev türleri ve yürütme mantığı.

Projede iki farklı süre profiline sahip görev türü bulunur:
1. image_resize: Görüntü boyutlandırma / filtreleme simülasyonu (doğrusal maliyet)
2. matrix_compute: Yoğun sayısal matris hesaplama simülasyonu (hafif doğrusal olmayan maliyet)
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict

SUPPORTED_TASK_TYPES = ("image_resize", "matrix_compute")


def validate_task(task_type: str, input_size: float) -> None:
    if task_type not in SUPPORTED_TASK_TYPES:
        raise ValueError(
            f"Geçersiz görev türü '{task_type}'. Desteklenenler: {SUPPORTED_TASK_TYPES}"
        )
    if input_size <= 0:
        raise ValueError("input_size 0'dan büyük olmalıdır.")


def compute_base_duration_seconds(task_type: str, input_size: float) -> float:
    """Standart hızdaki (speed_factor=1.0) bir worker üzerinde temel çalışma süresi (sn).

    - image_resize: sabit 0.08 sn hazırlık + birim başına 0.09 sn
    - matrix_compute: sabit 0.05 sn hazırlık + (input_size ** 1.25) * 0.08 sn
    """
    validate_task(task_type, input_size)
    if task_type == "image_resize":
        return 0.08 + 0.09 * float(input_size)
    if task_type == "matrix_compute":
        return 0.05 + 0.08 * (float(input_size) ** 1.25)
    raise ValueError(f"Bilinmeyen görev türü: {task_type}")


def execute_task(
    task_id: str,
    task_type: str,
    input_size: float,
    payload: Dict[str, Any] | None,
    worker_speed: float,
    cpu_load_factor: float = 1.0,
) -> Dict[str, Any]:
    """Görevi deterministik olarak çalıştırır ve çıktı özetini döndürür."""
    validate_task(task_type, input_size)
    effective_speed = max(0.05, float(worker_speed))
    base_seconds = compute_base_duration_seconds(task_type, input_size)
    target_duration = (base_seconds / effective_speed) * max(1.0, float(cpu_load_factor))

    start = time.monotonic()
    # Deterministik özet (checksum) üretimi
    digest_input = f"{task_id}:{task_type}:{input_size}:{payload or {}}".encode("utf-8")
    checksum = hashlib.sha256(digest_input).hexdigest()[:16]

    # Küçük parçalar halinde uyuyarak iptal/kapanma sinyallerine duyarlı kal
    remaining = target_duration - (time.monotonic() - start)
    while remaining > 0:
        sleep_slice = min(0.02, remaining)
        time.sleep(sleep_slice)
        remaining = target_duration - (time.monotonic() - start)

    actual_duration = time.monotonic() - start
    return {
        "checksum": checksum,
        "task_type": task_type,
        "input_size": input_size,
        "actual_worker_seconds": round(actual_duration, 4),
    }
