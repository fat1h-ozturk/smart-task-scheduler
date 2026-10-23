# Makine Öğrenmesi Destekli, Arızalara Dayanıklı Dağıtık Görev Zamanlama Sistemi

## 1. Proje özeti

Bu proje, bir koordinatörün işleri birden fazla çalışan bilgisayara dağıttığı ve çalışanların görevleri yürüttüğü küçük bir dağıtık görev sistemi geliştirmeyi hedefler. Sistem, görevlerin farklı makinelerdeki tahmini çalışma süresini kullanarak zamanlama yapar. Çalışan yanıt vermeyi keserse üzerindeki görevler zaman aşımından sonra yeniden kuyruğa alınır.

Projenin araştırma sorusu:

> Geçmiş çalıştırmalardan öğrenilen görev süresi tahminlerini kullanan bir zamanlayıcı, heterojen çalışanlardan oluşan bir havuzda klasik zamanlayıcılara kıyasla toplam tamamlanma süresini veya görev bekleme süresini azaltıyor mu?

Modelin daha iyi sonuç vermesi önceden varsayılmamalı. Sonuç, hangi iş yüklerinde ve hangi koşullarda yarar ya da zarar sağladığını gösterebilir.

## 2. Problem ve hedefler

Çalışan makineler CPU, bellek ve anlık yük bakımından farklı olabilir. Round-robin gibi basit bir yöntem bu farkları ve kuyrukları dikkate almaz. Bir çalışan kapanırsa üzerinde yürüyen görev de yarıda kalabilir.

Sistem iki ayrı hedefi ele alır:

1. **Zamanlama/verimlilik:** Görevi uygun çalışana atamak; toplam bitirme süresi ve bekleme süresini iyileştirmeye çalışmak.
2. **Hata toleransı:** Çalışan kaybolduğunda görevini tekrar çalıştırılabilir hale getirmek ve sonucu birden fazla kez uygulamamaya çalışmak.

### Kapsama dahil

- Bir koordinatör servisi ve birden fazla worker süreci.
- Önceden tanımlanmış 2–3 deterministik görev türü.
- Görev gönderme, atama, heartbeat, sonuç bildirimi ve yeniden deneme akışı.
- Round-robin, en kısa kuyruk ve ML destekli zamanlayıcı.
- Deney verilerinin ve görev olaylarının kaydı.
- Kontrollü worker arızası deneyi.
- Sonuçları gösteren basit komut satırı raporu veya küçük panel (çekirdek tamamlandıktan sonra).

### Kapsam dışı

- Koordinatörün yüksek erişilebilirliği veya Raft ile çoğaltılması.
- Genel amaçlı, kullanıcı kodunu güvenli biçimde çalıştıran platform.
- Sınırsız çevrimiçi öğrenme, GPU zamanlaması, otomatik ölçekleme.
- Gerçek anlamda “tam bir kez” yürütme garantisi. Dağıtık sistemde worker sonucu kaydettikten hemen önce/sonra kapanabilir; tasarım en az bir kez yürütmeyi kabul edip yinelenen sonuç etkisini sınırlar.

## 3. Başarı ölçütleri

Proje başarılı sayılabilmek için modelin mutlaka kazanması gerekmez. Aşağıdaki çıktılar somut ve tekrarlanabilir olmalıdır:

- Aynı iş yükünün üç zamanlayıcıyla çalıştırılması.
- Çalışan kaybı senaryosunda görevin tekrar atanmasının gösterilmesi.
- Her görevin yaşam döngüsünün kimlik ve zaman damgalarıyla izlenebilmesi.
- Tahmin hatasının ve sistem performans ölçülerinin raporlanması.
- Deneylerin yeniden çalıştırılabilir biçimde belgelenmesi.

Ölçümler:

| Ölçüm | Tanım |
|---|---|
| Makespan | Deneydeki ilk işin başlama anından son işin bitişine kadar geçen süre |
| Ortalama bekleme | Görevin kuyruğa alınması ile çalışmaya başlaması arasındaki süre |
| P95 bekleme / tamamlanma | Gözlemlerin yüzde 95'inin altında kaldığı süre; uç değer etkisini gösterir |
| Worker kullanımı | Çalışanların meşgul olduğu sürenin toplam uygun süreye oranı |
| Tahmin hatası | MAE ve mümkünse RMSE; eğitim dışı gözlemlerde hesaplanır |
| Kurtarma süresi | Worker kaybından arızalı görevin yeniden atanmasına kadar geçen süre |
| Yeniden deneme sayısı | Arıza nedeniyle tekrar çalıştırılan görev sayısı |

Birincil sonuç olarak **makespan**, ikincil sonuçlar olarak ortalama/P95 bekleme ve worker kullanımı seçilebilir. Çok sayıda metriğe bakıp yalnızca olumlu olanı öne çıkarmamak için bu seçim deneylerden önce raporda belirtilmelidir.

## 4. Önerilen mimari

```text
İstemci / deney sürücüsü
          |
          v
   Koordinatör API ---- Kalıcı görev deposu
          |                    |
     Zamanlayıcı <--- Worker durumu / kuyruk görünümü
          |
   Worker A, B, C ...
   (heartbeat, görev al, çalıştır, sonuç bildir)
```

### Koordinatör sorumlulukları

- Yeni görevi doğrulamak ve benzersiz `task_id` atamak.
- Görev durumunu kalıcı depoda tutmak.
- Uygun worker seçmek ve görevi bir lease/son kullanma zamanı ile atamak.
- Worker heartbeat'lerini izlemek.
- Lease süresi dolunca görevi tekrar kuyruğa almak veya başarısızlık durumuna geçirmek.
- Sonuç bildirimlerini doğrulamak; aynı görevin tamamlanma etkisini ikinci kez uygulamamak.
- Deney ve olay kayıtlarını üretmek.

### Worker sorumlulukları

- Koordinatöre düzenli heartbeat göndermek; kimlik, kapasite ve mevcut yükü bildirmek.
- Atanan görevi almak ve başlama/bitme bilgisini raporlamak.
- Görev çıktısını ve hata bilgisini bildirmek.
- Kontrollü kapanma ve deney amaçlı zorla durdurma senaryolarını desteklemek.

### Veri modeli taslağı

**Task:** `task_id`, `task_type`, `input_size`, `payload`, `status`, `attempt`, `created_at`, `assigned_worker`, `lease_until`, `started_at`, `finished_at`, `result`, `error`.

**Worker:** `worker_id`, `last_heartbeat`, `status`, `cpu_load`, `free_memory`, `capacity_hint`, `active_task`, `queue_estimate`.

**Task event:** `event_id`, `task_id`, `worker_id`, `attempt`, `event_type`, `timestamp`, `metadata`.

Görev durumları en azından `queued`, `running`, `succeeded`, `failed` ve `retry_wait` olabilir. Geçişler tek bir yerde tanımlanmalı; geçersiz durum geçişleri reddedilmelidir.

## 5. Zamanlayıcıların tanımı

Karşılaştırma adil olmalı: tüm yöntemler aynı worker uygunluk bilgisini ve aynı görev akışını görmelidir.

### A. Round-robin

Uygun worker'lar arasında sırayla seçim yapar. Basit taban çizgisidir. Worker uygun değilse atlanır.

### B. En kısa kuyruk

En az bekleyen görevi veya en düşük tahmini kuyruk iş yükü olan uygun worker'ı seçer. Yalnızca görev adedi kullanılırsa farklı boyuttaki görevleri ayırt edemez; mümkünse kuyruk iş yükü, bilinen/ortalama sürelerle saniye cinsinden tahmin edilir. Kullanılan çeşidi dokümante edin.

### C. ML destekli tahmini tamamlanma

Her uygun worker için görev süresini tahmin eder ve yaklaşık bitiş skorunu hesaplar:

`score(worker, task) = worker_queue_remaining_seconds + predicted_task_seconds`

En düşük skorlu worker seçilir. Worker uygunluğu ve kapasite kısıtları skordan önce uygulanır. Eşitliklerde deterministik bir bağlayıcı kural (ör. worker kimliği veya round-robin) kullanılır.

İlk model olarak Random Forest Regressor makul bir adaydır; küçük veri setinde doğrusal regresyon ve görev türü ortalaması gibi basit bir karşılaştırma da yararlı olabilir. Model karmaşıklığı veri miktarını aşmamalıdır.

### Önemli adalet/karşılaştırma ayrıntısı

En kısa kuyruk taban çizgisi mümkün olduğunca adil biçimde süre tahminini kullanmalı veya ayrıca “yalnızca görev sayısı” sürümü olarak açıkça tanımlanmalıdır. Aksi halde ML yönteminin kazancı modelden değil, daha anlamlı kuyruk ölçüsünden kaynaklanabilir. Deney tablosunda hangi varyantın kullanıldığı belirtilmelidir.

## 6. ML verisi ve özellikler

### Girdi özellikleri

- `task_type` (kategorik; ör. resize, compress, numeric)
- Görev boyutu (byte, piksel sayısı, eleman sayısı gibi türe uygun nicel ölçü)
- Worker kimliği veya worker kapasite sınıfı
- Atama anındaki CPU yükü ve boş RAM
- Kuyrukta bekleyen işlerin tahmini kalan süresi
- Worker'ın benzer görev türlerindeki geçmiş performansı (yalnızca geçmiş kayıtlar)

### Hedef değer

Görevin worker üzerinde fiilen çalıştığı süre. Başlama/bitme saatleri tek bir otoriteden (koordinatör) kaydedilirse saat senkronizasyonu sorunları azalır. Süre ölçümü ve birimler tüm görevlerde tutarlı olmalıdır.

### Veri sızıntısından kaçınma

- Test verisini model seçimi ve eğitim sırasında kullanmayın.
- Rastgele satır bölmek, aynı deney yükünün benzer kayıtlarını iki tarafa dağıtabilir. Mümkünse deney koşusu veya zaman dilimi bazında eğitim/test ayırın.
- Performans özelliği, tahmin edilen görevin sonucunu içermemeli; atama anında gerçekten bilinebilen verilerle sınırlı olmalı.
- Worker kimliği modele ekleniyorsa, görülmemiş bir worker'a genelleme iddiası yapılmamalıdır.
- Çevrimiçi güncelleme ilk sürümde gerekli değil. Veriyi topla, eğitim kümesiyle modeli eğit, ayrılmış test kümesinde değerlendir ve modeli zamanlayıcıda sabit sürüm olarak kullan.

### Soğuk başlangıç

İlk görevlerde geçmiş veri bulunmayacak. Basit bir başlangıç politikası belirleyin: görev türü genel ortalaması, sentetik ön eğitim verisi yerine kısa bir kalibrasyon turu veya sabit güvenli tahmin. Soğuk başlangıç dönemindeki sonuçları ayrıca raporlayın.

## 7. Arıza toleransı ve sonuç tekrarları

Worker heartbeat'i belirli aralıklarla gelir. Birkaç ardışık heartbeat kaçırıldığında worker `suspect`, zaman aşımında `unavailable` sayılır. Tek bir kaçırılmış heartbeat nedeniyle hemen görev yeniden atamak, yavaş ağda aynı görevin eşzamanlı iki kopyasını doğurabilir. Heartbeat aralığı ve timeout değerleri deney konfigürasyonunda görünür olmalı.

Görev ataması lease ile sınırlanır. Lease sona erdiğinde koordinatör görev denemesini geçersiz sayıp yeniden kuyruğa alabilir. Worker geç dönerse koordinatör deneme numarası/lease token kontrolüyle eski denemenin yeni durumu ezmesini engeller.

Görevler ilk sürümde **en az bir kez** yürütülebilir. Bu, arıza sırasında görevin birden fazla çalıştırılması ihtimalini kabul eder. Sonuç yazımı `task_id` ve deneme/sonuç anahtarıyla yinelenen etkiye karşı korunmalıdır. Örnek görevlerin yan etkisiz (deterministik hesaplama ve çıktı üretimi) olması bu kapsamı yönetilebilir tutar.

## 8. Deney tasarımı

### İş yükü

- En az iki, tercihen üç görev türü; her tür için farklı girdi boyutları.
- Küçük, orta ve büyük görevlerden oluşan sabit bir iş listesi.
- Ani yük ve kademeli yük gibi en az iki geliş biçimi.
- Heterojen worker profilleri: ör. yapay kapasite katsayısı veya kontrollü CPU kısıtı. Gerçek farklı makineler kullanılabiliyorsa donanım bilgisi kaydedilmeli.

### Deney koşulları

1. Arızasız temel koşul.
2. Yüksek kuyruk/heterojen kapasite koşulu.
3. Görev sürerken bir worker'ın durdurulduğu arıza koşulu.
4. Soğuk başlangıç veya az eğitim verisi koşulu (zaman kalırsa).

Her algoritma için aynı görev listesi ve koşullar kullanılmalı. Rastgelelik varsa seed kaydedilmeli. Ölçümleri birkaç tekrar üzerinden özetleyin; ortalama ile birlikte dağılımı/standart sapmayı veya güven aralığını sunun. Deneyleri tek tek elle çalıştırmak yerine bir deney sürücüsü konfigürasyon ve sonuç dosyası üretsin.

Sonuç tablosu örneği:

| Koşul | Zamanlayıcı | Makespan | Ortalama bekleme | P95 bekleme | MAE | Kurtarma süresi |
|---|---|---:|---:|---:|---:|---:|
| Heterojen, arızasız | Round-robin |  |  |  | — | — |
| Heterojen, arızasız | En kısa kuyruk |  |  |  | — | — |
| Heterojen, arızasız | ML tahmini |  |  |  |  | — |

Arızalı senaryoda zamanlayıcı karşılaştırmasına ek olarak yeniden deneme ve mükerrer sonuç kontrolleri raporlanır.

## 9. Altı haftalık ilerleme planı

| Hafta | Hedef | Somut çıktı / geçiş ölçütü |
|---|---|---|
| 1 | Kapsamı sabitle, görev türlerini ve protokolü seç, proje iskeletini kur | README, görev/worker veri modeli, tek makinede koordinatör ve worker taslağı |
| 2 | Uçtan uca dikey dilim: görev gönder, çalıştır, sonucu kaydet | Bir görev queued → running → succeeded akışını tamamlar; olay kaydı vardır |
| 3 | Worker havuzu, kuyruklama, heartbeat ve üç temel zamanlayıcı | Aynı sabit yük round-robin ve en kısa kuyrukla tamamlanır; ML şimdilik tahmin arayüzü/sabit baseline olabilir |
| 4 | Veri toplama, özellik çıkarımı ve model eğitimi | Eğitim/test ayrımı belgeli; MAE/RMSE raporu; ML scheduler tahmini kullanır |
| 5 | Lease, timeout, yeniden atama ve idempotent sonuç işleme; arıza deneyleri | Worker öldürülünce görev yeniden denenir; geç gelen eski deneme yeni sonucu ezmez |
| 6 | Deneyleri tekrarla, sonuçları analiz et, rapor ve demo hazırla | Karşılaştırma tabloları/grafikleri, sınırlılıklar, tekrarlanabilir çalıştırma yönergesi |

### İlerleme kuralı

Önce en küçük uçtan uca sistemi bitirin; model ve paneli bunun üzerine ekleyin. İkinci hafta sonunda görev bir worker'da çalışıp sonucu saklayamıyorsa yeni özellik eklemek yerine bu dikey akışı tamamlayın. Beşinci haftaya gelindiğinde çekirdek ve arıza akışı bitmediyse paneli bırakıp deney ve raporlamaya öncelik verin.

## 10. Teknik seçimler (öneri, zorunlu değil)

Programlama dili dersin gereksinimine göre seçilmeli. Python hızlı prototipleme ve scikit-learn için uygundur; ders başka bir dil istiyorsa koordinatör/worker o dilde yazılıp model ayrı bir süreç veya servis olarak sunulabilir. Başlangıçta mikroservis sayısını artırmayın.

- İletişim: HTTP/JSON veya gRPC; ders kapsamı ve dil desteğine göre biri seçilsin.
- Kalıcılık: ilk sürümde SQLite yeterli olabilir; eşzamanlılık ve çalışma ortamı sınırları erken denenmeli.
- Deney kayıtları: CSV/JSONL veya veritabanından dışa aktarılan tablo.
- Çalıştırma: önce tek makinede çoklu worker süreçleri; ardından LAN'da farklı bilgisayarlarda dağıtık çalışma.
- Panel: ancak temel deneyler tamamlandıktan sonra basit grafik/rapor.

Önerilen modül ayrımı:

```text
coordinator/       API, görev deposu, yaşam döngüsü, zamanlayıcı arayüzü
worker/            heartbeat, görev yürütme, sonuç bildirimi
tasks/             deterministik görev türleri ve girdi doğrulama
scheduler/         round_robin, shortest_queue, ml_predictor
experiments/       sabit workload, arıza enjeksiyonu, metrik çıkarma
models/            eğitim betiği, model dosyası ve özellik şeması
docs/              mimari, protokol, deney ve sonuç notları
```

## 11. Riskler ve azaltma yolları

| Risk | Etkisi | Azaltma |
|---|---|---|
| Yetersiz eğitim verisi | ML tahminleri gürültülü olur | Görev türü/boyut matrisiyle kontrollü kalibrasyon; basit baseline; belirsizliği raporlama |
| Modelin klasik yöntemi geçememesi | Beklenen performans kazanımı yok | Proje sorusunu koşullara göre analiz etmek; sonuç başarısızlığı bilimsel bulgudur |
| Süre ölçümünün gürültüsü | Karşılaştırma güvenilmez olur | Aynı ortam, sabit seed, tekrarlar, tek saat kaynağı, arka plan yükünü kaydetme |
| Ağ gecikmesi/heartbeat dalgalanması | Gereksiz yeniden deneme | Birkaç kaçırılmış heartbeat ve lease; timeout duyarlılık deneyi |
| Worker kaybında çift çalışma | Yan etki veya yarış | Deneme token'ı, geçersiz eski lease'i reddetme, idempotent sonuç anahtarı |
| Her şeyi aynı anda geliştirme | Çekirdek akış bitmez | Haftalık geçiş ölçütleri; paneli son aşamaya koyma; Raft ve otomatik öğrenmeyi kapsam dışı tutma |
| En kısa kuyruk kıyasının adaletsizliği | ML kazancı yanlış yorumlanır | Algoritmaları açıkça tanımlama; görev sayısı ve süre bazlı kuyruk varyantlarını ayırma |

## 12. Teslim edilecekler

- Kaynak kod ve kurulum/çalıştırma yönergesi.
- Mimari ve görev durum geçişlerini anlatan kısa tasarım belgesi.
- Model eğitim ve değerlendirme betiği; özellik tanımları.
- Deney konfigürasyonları ve ham sonuçlar.
- Üç zamanlayıcının karşılaştırma tablosu/grafikleri.
- Worker arızası demosu ve toparlanma ölçümü.
- Sonuç, sınırlılıklar ve gelecekteki çalışmalar bölümleri olan rapor.
- Kısa canlı demo veya kayıt: görev dağıtımı, bir worker'ın kapatılması, görevin yeniden tamamlanması.

## 13. Sunumda savunulacak noktalar

- Neden yalnızca görev sayısı yerine tahmini tamamlanma süresi kullanılıyor?
- ML özellikleri atama anında gerçekten bilinebiliyor mu?
- Eğitim ve test verisi nasıl ayrıldı; model yeni koşullara ne kadar genelliyor?
- Worker başarısızlığı nasıl tespit ediliyor ve timeout nasıl seçildi?
- Bir görev iki kez çalışırsa sistem ne yapıyor?
- ML hangi yüklerde yarar sağladı, hangi yüklerde sağlamadı?
- Deneyler aynı koşullarda tekrarlanabilir mi?

## 14. Son karar ve önerilen daraltma

Bu fikir ders projesi için yeterince derin; ancak dağıtık sistem, hata toleransı ve ML aynı anda zaman alır. Öncelik sırası şöyle olmalı:

1. Tek makinede coordinator-worker görev akışı.
2. Birden çok worker ve iki klasik scheduler.
3. Kalıcı görev durumu, heartbeat, lease ve yeniden deneme.
4. Ölçüm altyapısı ve sabit deney yükü.
5. Eğitim verisi, tahmin modeli ve ML scheduler.
6. Kontrollü arıza deneyleri, analiz, rapor ve varsa panel.

Zaman azalırsa panel, çevrimiçi öğrenme ve farklı görev türlerinin sayısı azaltılabilir. Görev yaşam döngüsü, en az iki klasik yöntemle adil karşılaştırma, bir ML tahmini ve en az bir worker arızası deneyi korunmalıdır.
