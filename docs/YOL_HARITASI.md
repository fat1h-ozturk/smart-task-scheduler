# 6 Haftalık Gerçekçi Proje Yol Haritası

## Hedef

Üç kişilik, ikinci sınıf bilgisayar mühendisliği ekibinin altı haftada tamamlayabileceği küçük ama gösterilebilir bir dağıtık görev sistemi geliştirmek. Sistem işleri birkaç worker'a dağıtacak, üç dağıtım yöntemini karşılaştıracak ve worker kapanınca görevi yeniden deneyecek.

**Temel araştırma sorusu:** Görev sürelerini tahmin eden basit bir model, heterojen worker'larda işleri klasik dağıtım yöntemlerinden daha kısa sürede tamamlıyor mu?

Modelin daha iyi çıkması şart değildir. Güvenilir deney ve doğru yorum proje başarısının parçasıdır.

## Başlangıçta kapsamı sabitleyin

Altı hafta boyunca aşağıdaki çekirdek kapsamı koruyun:

- Bir koordinatör ve 2–3 worker.
- İlk aşamada aynı bilgisayarda ayrı süreçler olarak çalışma; zaman kalırsa farklı bilgisayarlarda LAN denemesi.
- İki görev türü: örneğin görüntü boyutlandırma ve sayısal hesaplama. Gerçekten farklı süre profilleri oluşturmaları gerekir.
- Üç zamanlayıcı: round-robin, en kısa kuyruk ve modelin tahmini tamamlanma süresini kullanan yöntem.
- Worker heartbeat'i, görev zaman aşımı ve tekrar kuyruğa alma.
- Aynı sabit iş yükünde tekrarlanabilir karşılaştırma.

**İlk sürüm kapsamı dışında:** Raft, koordinatör yedekliliği, çevrimiçi model eğitimi, karmaşık web paneli, serbest kullanıcı kodu çalıştırma ve tam bir kez yürütme garantisi.

## Ekip içi sorumluluklar

Üç öğrenci kendi ana alanına sahip olsun; arayüzleri ve protokolü birlikte kararlaştırsın. Her hafta bütün ekip en az bir kez entegre sürümü çalıştırmalıdır.

| Rol | Ana sorumluluk | Birlikte kararlaştırılacak noktalar |
|---|---|---|
| Öğrenci A: Koordinatör | Görev API'si, görev durumları, kalıcı kayıt, zamanlayıcı arayüzü | Görev veri biçimi, durum geçişleri, atama/sonuç protokolü |
| Öğrenci B: Worker ve hata yönetimi | Worker süreci, görev çalıştırma, heartbeat, timeout ve yeniden deneme | Worker kimliği, heartbeat aralığı, lease/deneme numarası |
| Öğrenci C: Deney ve ML | Görev iş yükü, veri toplama, basit model, deney sürücüsü ve raporlama | Özellikler, eğitim/test ayrımı, metrikler ve deney koşulları |

Bu ayrım modül sahipliğini belirler; entegrasyon, kod inceleme ve sunum hazırlığını tek kişiye bırakmaz.

## Hafta-hafta plan

### 1. hafta — Tasarımı küçültün ve arayüzleri sabitleyin

**Yapılacaklar**

- Dersin dil ve kütüphane kısıtlarını kontrol edin; tek bir dil ve iletişim biçimi seçin.
- İki deterministik görev türünü seçin ve küçük/orta/büyük girdi örneklerini tanımlayın.
- Görev durumlarını belirleyin: `queued`, `running`, `succeeded`, `failed`.
- Koordinatör ile worker arasındaki mesajları ve JSON alanlarını kararlaştırın.
- Git deposu, çalıştırma yönergesi, issue listesi ve haftalık kısa toplantı düzeni oluşturun.
- Herkes kendi modülünün iskeletini açsın; ilk günlerde entegrasyon sözleşmesini yazılı hale getirin.

**Hafta sonu çıktısı**

- Bir sayfalık mimari ve protokol notu.
- Seçilmiş görev türleri ve örnek girdiler.
- Tek komutla boş uygulamaların başlatılabildiği proje iskeleti.

**Geçiş ölçütü:** Herkes görevin nasıl gönderileceği, worker'ın nasıl alacağı ve sonucun hangi biçimde döneceği konusunda aynı anlayışta.

### 2. hafta — Tek görevi uçtan uca çalıştırın

**Yapılacaklar**

- İstemciden koordinatöre görev gönderin.
- Koordinatör görevi sıraya alsın ve bir worker'a versin.
- Worker görevi çalıştırıp sonucu koordinatöre bildirsin.
- Durum ve zaman damgalarını kaydedin.
- Önce bir worker ve tek görevle başlayın; sonra görev türlerinin ikisini de deneyin.

**Hafta sonu çıktısı**

- Çalışan dikey dilim: görev gönderme → çalıştırma → sonucu görme.
- En azından görev kimliği, durum ve hata bilgisini içeren günlük kayıtları.

**Geçiş ölçütü:** Temiz kurulumda ekip üyesi yönergeyi izleyerek örnek görevi çalıştırabiliyor. Bu ölçüt sağlanmadan yeni özellik eklemeyin.

### 3. hafta — Worker havuzu ve klasik zamanlayıcılar

**Yapılacaklar**

- İki veya üç worker'ı aynı anda çalıştırın.
- Zamanlayıcı arayüzünü oluşturun ve round-robin ekleyin.
- En kısa kuyruk yöntemini ekleyin. İlk sürümde kuyruk görev adedini kullanıyorsa bunu raporda açıkça belirtin.
- Atama, başlangıç ve bitiş sürelerini kaydedin.
- Deney sürücüsünün sabit bir iş listesini çalıştırmasını sağlayın.

**Hafta sonu çıktısı**

- Aynı görev listesinin birden fazla worker'da çalışması.
- Round-robin ve en kısa kuyrukla ilk karşılaştırma.

**Geçiş ölçütü:** Aynı iş yükü seçilen klasik zamanlayıcıyla baştan sona tamamlanıyor; görev kaybı veya durum uyuşmazlığı gözlenmiyor.

### 4. hafta — Veri toplayın ve basit tahmin modelini ekleyin

**Yapılacaklar**

- Görev türü, girdi büyüklüğü, worker profili/yükü ve gerçek çalışma süresini kaydedin.
- Kontrollü tekrarlarla kullanılabilir örnek veri toplayın; verinin az olabileceğini göz önünde bulundurun.
- Basit karşılaştırma tahmini (ör. görev türü ortalaması) ve Random Forest gibi bir model deneyin.
- Eğitim ve test kayıtlarını ayırın; aynı deney tekrarlarının iki kümeye dağılmamasına dikkat edin.
- Tahmin edilen süre + kuyrukta bekleyen tahmini süre ile worker seçen zamanlayıcıyı bağlayın.
- MAE veya RMSE hesaplayın.

**Hafta sonu çıktısı**

- Modelin nasıl eğitileceğini yeniden çalıştırılabilir biçimde gösteren betik.
- ML zamanlayıcısının tahmin kullanarak atama yapması.
- Eğitim/test ayrımı ve ilk tahmin hatası raporu.

**Geçiş ölçütü:** Model yoksa sistem sabit tahmin/baseline ile çalışmaya devam edebiliyor; ML bileşeni ana görev akışını kilitlemiyor.

### 5. hafta — Worker arızası ve yeniden deneme

**Yapılacaklar**

- Worker heartbeat göndermeyi bıraktığında bunu tespit edin.
- Sürenin dolmasını bekleyip worker'ı geçici olarak kullanılamaz sayın.
- Üzerindeki görevi yeni deneme numarasıyla kuyruğa alın ve başka worker'a atayın.
- Eski worker geç sonuç yollarsa, eski denemenin güncel sonucu ezmesini engelleyin.
- Aynı görev sonucunun iki kere kaydedilmediğini kontrol edin.
- Bir worker'ı görev ortasında durdurarak arıza demosu yapın.

**Hafta sonu çıktısı**

- Görev ortasında worker kapanınca görevin başka worker'da tamamlandığı gösterim.
- Arıza tespit ve toparlanma sürelerinin kaydı.

**Kapsam daraltma kararı:** Bu haftanın ortasında çekirdek arıza akışı tamamlanmadıysa panel geliştirmeyin; sonraki haftada önce bunu bitirin.

### 6. hafta — Adil deney, sonuçlar ve teslim

**Yapılacaklar**

- İş yükünü ve deney koşullarını sabitleyin; rastgelelik varsa seed kaydedin.
- Üç zamanlayıcıyı aynı koşullarda birkaç kez çalıştırın.
- Arızasız ve worker arızalı deneyleri ayrı analiz edin.
- Makespan ve ortalama/P95 bekleme süresini raporlayın; ML için tahmin hatasını, arıza deneyinde kurtarma süresini ekleyin.
- Sonuçların sınırlılıklarını yazın: veri miktarı, test ortamı, worker profili ve modelin genellenebilirliği.
- Çalıştırma yönergesini, demo akışını ve sunumu tamamlayın.

**Hafta sonu çıktısı**

- Tekrar çalıştırılabilir deney komutu/konfigürasyonu.
- Karşılaştırma tablosu ve bir iki anlaşılır grafik.
- Rapor, kurulum yönergesi ve kısa demo.

## Deneyleri yönetme biçimi

Her deney için kaydedin:

- Zamanlayıcı adı ve sürümü.
- Görev listesi, girdi büyüklükleri ve sıra.
- Worker sayısı/profili ve deney seed'i.
- Arıza olup olmadığı ve arıza zamanı.
- Makespan, bekleme süreleri, tahmin hatası ve yeniden deneme bilgileri.

Üç yöntem için aynı iş listesini kullanın. Mümkünse her koşulu birkaç kez tekrarlayıp yalnızca en iyi koşuyu seçmek yerine tüm sonuçların ortalamasını ve yayılımını raporlayın. En kısa kuyruk yöntemi görev adedine bakıyorsa, ML'nin avantajının bu farklı kuyruk ölçüsünden kaynaklanabileceğini tartışın.

## Haftalık ekip çalışma ritmi

- Haftanın başında her kişi için en fazla 2–3 somut iş seçin.
- Haftanın ortasında arayüz üzerinden entegrasyon yapın; sürpriz birleşmeyi son güne bırakmayın.
- Hafta sonunda çalışan sürümü beraber gösterin ve geçiş ölçütünü kontrol edin.
- Bloklanan işi hemen görünür kılın; kapsamı küçültme kararını aynı hafta verin.
- Herkes en az bir başka modülde kod incelemesi veya entegrasyon katkısı yapsın.

## En önemli riskler ve karar eşikleri

| Ne zaman fark edilirse | Karar |
|---|---|
| 2. hafta sonunda uçtan uca tek görev yürümüyor | ML'yi erteleyin; yalnızca görev akışını tamamlayın |
| 3. hafta sonunda çoklu worker kararlı değil | Farklı bilgisayarlarda çalıştırmayı erteleyip tek makinede süreçlerle devam edin |
| 4. hafta sonunda veri az veya tahmin gürültülü | Basit baseline ile kıyaslayın; modeli küçük tutun ve sonucu sınırlı olarak raporlayın |
| 5. hafta ortasında arıza/yeniden deneme tamamlanmadı | Panel ve ek özellikleri tamamen bırakın |
| Son haftada sonuçlar dalgalı | Daha çok tekrar yapın; olumlu görünen koşuyu seçmek yerine yayılımı gösterin |

## Teslim kontrol listesi

- [ ] Temiz ortamda kurulum ve çalıştırma yönergesi izlenebiliyor.
- [ ] En az iki worker görev alıp sonuç döndürüyor.
- [ ] Round-robin, en kısa kuyruk ve ML tahmini kullanan yöntem mevcut.
- [ ] Worker kapanınca görev yeniden atanıyor.
- [ ] Yeniden denemeler ve sonuç kayıtları görev kimliğiyle izleniyor.
- [ ] Eğitim/test ayrımı ve tahmin hatası açıklanıyor.
- [ ] Aynı iş yükünde tekrar edilmiş algoritma karşılaştırması var.
- [ ] Sonuçlar, sınırlılıklar ve demo akışı hazır.

## Son öneri

Önce çalışan en küçük dağıtık sistemi bitirin; sonra model ve arıza yönetimini bu akışa ekleyin. Altı haftalık projenin değerini çok sayıda özellik değil, çalışan prototip, adil karşılaştırma ve ölçümlere dayalı açıklama belirler. Panel yalnızca bu üçü tamamlandıktan sonra kalan zamana göre yapılmalıdır.
