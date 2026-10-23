# Makine Öğrenmesi Destekli, Arızalara Dayanıklı Dağıtık Görev Zamanlama Sistemi

Bu proje, heterojen (farklı işlem hızlarına sahip) çalışan süreçlerden (*worker*) oluşan bir havuzda görevlerin hangi çalışana atanacağına karar veren bir **Koordinatör** servisi ve **Zamanlayıcı (Scheduler)** altyapısı sunar.

## Araştırma Sorusu
> Geçmiş çalıştırmalardan öğrenilen görev süresi tahminlerini kullanan bir zamanlayıcı (`ml_predictor`), heterojen çalışanlardan oluşan bir havuzda klasik zamanlayıcılara (`round_robin`, `shortest_queue`) kıyasla toplam tamamlanma süresini (*makespan*) ve görev bekleme süresini azaltıyor mu?

---

## Proje Mimarisi ve Dizin Yapısı

```text
.
├── coordinator/       # HTTP JSON API sunucusu, SQLite görev deposu, lease ve arıza izleyicisi
│   ├── server.py
│   └── store.py
├── worker/            # Heartbeat gönderen, görev çekip deterministik yürüten çalışan süreç
│   └── agent.py
├── tasks/             # Deterministik görev türleri (image_resize, matrix_compute)
│   └── runner.py
├── scheduler/         # Zamanlayıcı algoritmaları (Round-Robin, Shortest Queue, ML Predictor)
│   └── schedulers.py
├── models/            # Görev süresi tahmin modeli (Ridge/Polinom Regresyon) ve eğitim betiği
│   ├── predictor.py
│   └── train.py
├── experiments/       # Tek komutla 3 algoritmayı ve worker arıza senaryosunu yarıştıran sürücü
│   └── run_demo.py
└── docs/              # Proje notu, 6 haftalık yol haritası ve sunum belgeleri
```

---

## Hızlı Başlangıç (Tek Komutla Sunum ve Deney Demosu)

Harici bir web çatısı kurulumuna gerek kalmadan (Python standart kütüphanesi + `numpy` ile) tüm sistemi, model eğitimini, 3 zamanlayıcı karşılaştırmasını ve worker çökme (arıza toleransı) deneyini tek komutla çalıştırabilirsiniz:

```bash
python3 -m experiments.run_demo
```

Bu komut sırasıyla:
1. Kalibrasyon verisiyle görev süresi tahmin modelini eğitir (`models/trained_model.json`) ve test kümesi **MAE / RMSE** değerlerini hesaplar.
2. Arka planda **Koordinatör** ve 3 farklı hızda **Worker** (`worker-A: 1.0x`, `worker-B: 0.45x`, `worker-C: 0.20x`) başlatır.
3. Aynı 12 görevlik karışık iş yükünü **Round-Robin**, **Shortest Queue** ve **ML Predictor** ile çalıştırıp karşılaştırma tablosunu ekrana basar.
4. **Arıza Toleransı Demosu:** Görev ortasında `worker-B`'yi durdurur, koordinatörün *heartbeat/lease* zaman aşımıyla yarım kalan işi `attempt=2` olarak başka worker'a devrettiğini ve eski worker'dan gelen gecikmeli sonucun (`attempt=1`) reddedildiğini gösterir.

---

## Ayrı Terminallerde (veya Ayrı Bilgisayarlarda) Çalıştırma

Sunumda bileşenleri ayrı terminallerde canlı göstermek isterseniz:

**1. Modeli Eğitin:**
```bash
python3 -m models.train
```

**2. Koordinatörü Başlatın (Terminal 1):**
```bash
python3 -m coordinator.server --host 0.0.0.0 --port 8000 --scheduler ml_predictor
```

**3. Worker'ları Başlatın (Terminal 2, 3, 4):**
```bash
python3 -m worker.agent --id worker-A --speed 1.00 --coordinator http://127.0.0.1:8000
python3 -m worker.agent --id worker-B --speed 0.45 --coordinator http://127.0.0.1:8000
python3 -m worker.agent --id worker-C --speed 0.20 --coordinator http://127.0.0.1:8000
```
*(Farklı bilgisayarlarda çalıştırırken `127.0.0.1` yerine Koordinatör bilgisayarın yerel IP adresini yazmanız yeterlidir.)*
