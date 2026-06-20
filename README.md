# SoileTranslate Ses

SoileTranslate Ses, bilgisayar seslerini (oyun, video) ve mikrofon girişinizi gerçek zamanlı olarak çeviren, modern ve kullanıcı dostu bir masaüstü uygulamasıdır.

## 🚀 Özellikler

- **Çift Yönlü Çeviri**: 
    - PC Sesini (İngilizce -> Türkçe) yakalar ve çevirir.
    - Mikrofonu (Türkçe -> İngilizce) bas-konuş sistemiyle yakalar ve çevirir.
- **Yüksek Performanslı AI**: 
    - Konuşma tanıma için `Faster-Whisper` (Base/Small modelleri) kullanır.
    - Çeviri için Meta'nın `NLLB-200` modelini kullanır.
- **Düşük Gecikme**: CPU üzerinde optimize edilmiş iş parçacığı yönetimi ile gerçek zamanlı çeviri sağlar.
- **Akıllı Ses Yakalama**: Voice Activity Detection (VAD) teknolojisi ile sadece konuşma olan anları işleyerek performansı maksimize eder.
- **Overlay (Ekran Üstü) Panel**: Oyun oynarken veya film izlerken dikkatinizi dağıtmadan çevirileri okuyabilmeniz için yarı saydam panel.

## 🛠 Kurulum

1. Depoyu klonlayın veya indirin.
2. `SoileTranslate_Ses_Baslat.bat` dosyasını çalıştırın.
    - Bu dosya otomatik olarak sanal ortamı (`.venv`) oluşturacak ve gerekli kütüphaneleri (PyQt5, Faster-Whisper, onnxruntime vb.) yükleyecektir.
3. Modeller ilk açılışta otomatik olarak indirilecektir.

## 📖 Kullanım

- **PC Sesi Çevirisi**: Panelden "Baslat" butonuna basın. Bilgisayarda çalan İngilizce sesler otomatik olarak Türkçe'ye çevrilip ekranın üst kısmında belirecektir.
- **Mikrofon Çevirisi**: İstediğiniz bas-konuş tuşunu seçin (Varsayılan: V). Tuşa basılı tutarak Türkçe konuşun, bıraktığınızda çeviriniz İngilizce olarak ekranın alt kısmında belirecektir.

## ⚙ Sistem Gereksinimleri

- Windows 10/11
- Python 3.10 veya üzeri
- Önerilen: 8GB+ RAM, Orta/Üst segment bir işlemci.

## 📄 Lisans

Bu proje eğitim ve kişisel kullanım amacıyla geliştirilmiştir.

---
*Geliştirici: Antigravity AI*
