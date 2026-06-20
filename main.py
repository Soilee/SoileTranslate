# -*- coding: utf-8 -*-
import os
import sys
import time
import ctypes
import threading
import gc

import numpy as np
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QPixmap
from PyQt5.QtWidgets import (
    QAction, QApplication, QComboBox, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QMenu, QPushButton, QProgressBar, QSystemTrayIcon, QVBoxLayout, QWidget
)

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
user32 = ctypes.windll.user32
SetWindowLongW = user32.SetWindowLongW
GetWindowLongW = user32.GetWindowLongW

DARK_STYLE = """
QWidget { background:#0d1117; color:#e6edf3; font-family:'Segoe UI'; font-size:13px; }
QGroupBox { border:1px solid #30363d; border-radius:8px; background:#161b22; margin-top:10px; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 6px; color:#58a6ff; font-weight:bold; }
QPushButton { border:1px solid #30363d; border-radius:8px; padding:10px 18px; font-weight:bold; }
QPushButton#btnStart { background:#238636; color:white; border-color:#2ea043; }
QPushButton#btnStart:hover { background:#2ea043; }
QPushButton#btnStop { background:#da3633; color:white; border-color:#f85149; }
QPushButton#btnStop:hover { background:#f85149; }
QPushButton#btnBoth { background:#1f6feb; color:white; border-color:#388bfd; }
QPushButton#btnBoth:hover { background:#388bfd; }
QPushButton:disabled { background:#222; color:#666; border-color:#333; }
QComboBox { background:#21262d; border:1px solid #30363d; border-radius:6px; padding:6px; color:#e6edf3; }
QProgressBar { border:1px solid #30363d; border-radius:5px; text-align:center; background:#21262d; }
QProgressBar::chunk { background:#1f6feb; }
QLabel#titleLabel { font-size:20px; font-weight:bold; color:#58a6ff; }
QLabel#logLabel { background:#161b22; border:1px solid #30363d; border-radius:6px; padding:8px; color:#7ee787; font-size:12px; }
QLabel#stateLabel { color:#8b949e; font-weight:bold; }
QLabel#stateActive { color:#3fb950; font-weight:bold; font-size:14px; }
QLabel#stateRecording { color:#f0883e; font-weight:bold; font-size:14px; }
"""


class AudioCapture:
    """PC ses yakalama (loopback)."""
    __slots__ = ('sample_rate', 'device_id', 'buffer', '_lock', '_running',
                 '_thread', '_record_error', 'last_sound_time',
                 'silence_threshold', 'silence_limit')

    def __init__(self, device_id=None, sample_rate=16000):
        self.sample_rate = sample_rate
        self.device_id = device_id if device_id is not None else ("soundcard", None)
        self.buffer = []
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._record_error = None
        self.last_sound_time = time.time()
        self.silence_threshold = 0.002
        self.silence_limit = 0.6

    def start(self):
        self._running = True
        self.buffer = []
        self._record_error = None
        self.last_sound_time = time.time()
        self._thread = threading.Thread(target=self._record_loopback, daemon=True)
        self._thread.start()

    def _record_loopback(self):
        co_initialized = False
        try:
            hr = ctypes.windll.ole32.CoInitializeEx(None, 0)
            co_initialized = hr in (0, 1)
            import soundcard as sc
            speakers = sc.all_speakers()
            idx = self.device_id[1] if isinstance(self.device_id, tuple) else None
            speaker = sc.default_speaker() if idx is None else speakers[idx]
            loopbacks = sc.all_microphones(include_loopback=True)
            mic = next((m for m in loopbacks if m.id == speaker.id), None) or \
                  next((m for m in loopbacks if m.name == speaker.name), None)
            if mic is None:
                raise RuntimeError(f"Loopback bulunamadi: {speaker.name}")
            frames = int(self.sample_rate * 0.1)
            with mic.recorder(samplerate=self.sample_rate) as recorder:
                while self._running:
                    data = recorder.record(numframes=frames)
                    mono = np.asarray(data, dtype=np.float32)
                    if mono.ndim > 1:
                        mono = mono.mean(axis=1)
                    with self._lock:
                        self.buffer.extend(mono)
                        if np.abs(mono).max(initial=0.0) > self.silence_threshold:
                            self.last_sound_time = time.time()
        except Exception as e:
            self._record_error = e
        finally:
            if co_initialized:
                ctypes.windll.ole32.CoUninitialize()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self.buffer = []

    def get_chunk(self):
        with self._lock:
            if not self.buffer:
                return None
            duration = len(self.buffer) / self.sample_rate
            silent = time.time() - self.last_sound_time > self.silence_limit
            if (duration > 0.9 and silent) or duration >= 1.6:
                chunk = np.array(self.buffer, dtype=np.float32)
                self.buffer = []
                return chunk
        return None


class MicrophoneCapture:
    """Mikrofon yakalama (push-to-talk)."""
    __slots__ = ('sample_rate', 'device_id', 'buffer', '_lock', '_stream', 'actual_rate')

    def __init__(self, device_id=None, sample_rate=16000):
        self.sample_rate = sample_rate
        self.device_id = device_id
        self.buffer = []
        self._lock = threading.Lock()
        self._stream = None
        self.actual_rate = sample_rate

    def start(self):
        import sounddevice as sd
        with self._lock:
            self.buffer = []
        
        # Oncelikle istenen hizi dene, olmazsa cihazin varsayilanini kullan
        try:
            sd.check_input_settings(device=self.device_id, samplerate=self.sample_rate, channels=1)
            self.actual_rate = self.sample_rate
        except Exception:
            try:
                device_info = sd.query_devices(self.device_id, 'input')
                self.actual_rate = int(device_info['default_samplerate'])
            except Exception:
                self.actual_rate = 44100 # Son care

        self._stream = sd.InputStream(
            samplerate=self.actual_rate, channels=1, dtype="float32",
            device=self.device_id, callback=self._callback,
            blocksize=int(self.actual_rate * 0.05)
        )
        self._stream.start()

    def stop(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        with self._lock:
            if not self.buffer:
                return None
            chunk = np.concatenate(self.buffer)
            self.buffer = []
        
        # Yeniden ornekleme (Resampling)
        if self.actual_rate != self.sample_rate and len(chunk) > 0:
            duration = len(chunk) / self.actual_rate
            num_samples = int(duration * self.sample_rate)
            if num_samples > 0:
                chunk = np.interp(
                    np.linspace(0, len(chunk), num_samples, endpoint=False),
                    np.arange(len(chunk)),
                    chunk
                ).astype(np.float32)

        peak = float(np.abs(chunk).max(initial=0.0))
        if 0.025 < peak < 0.45:
            chunk = chunk * (0.65 / peak)
        return chunk.astype(np.float32)

    def _callback(self, indata, frames, time_info, status):
        with self._lock:
            self.buffer.append(indata[:, 0].copy())


class SpeechEngine:
    def __init__(self, model_name="base"):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(
            model_name, device="cpu", compute_type="int8",
            cpu_threads=4, num_workers=2
        )

    def transcribe(self, audio, language="en"):
        audio = np.asarray(audio, dtype=np.float32)
        audio = np.nan_to_num(audio)
        peak = float(np.abs(audio).max(initial=0.0))
        rms = float(np.sqrt(np.mean(audio ** 2))) if len(audio) else 0.0
        if len(audio) < 16000 * 0.30 or peak < 0.008 or rms < 0.0018:
            return ""
        if peak > 1.0:
            audio = audio / peak
        prompt = None
        hotwords = None
        if language == "tr":
            prompt = "Turkce konusan bir kisi. Duzgun ve net bir Turkce."
            hotwords = "aptal salak mal orospu amk aq siktir pic yarrak amcik got bok sik kelime"

        segments, _ = self.model.transcribe(
            audio, language=language, task="transcribe",
            initial_prompt=prompt, hotwords=hotwords,
            condition_on_previous_text=False,
            temperature=[0.0, 0.2] if language == "tr" else 0.0,
            beam_size=2, # Dogruluk icin 2 yapildi (eskiden 1'di)
            no_speech_threshold=0.62 if language == "tr" else 0.72,
            log_prob_threshold=-1.2 if language == "tr" else -0.8,
            compression_ratio_threshold=2.3 if language == "tr" else 2.0,
            vad_filter=True, vad_parameters=dict(min_silence_duration_ms=400),
        )
        return " ".join(s.text.strip() for s in segments).strip()


class TranslationEngine:
    MODEL_NAME = "facebook/nllb-200-distilled-600M"
    MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "nllb-200-ct2")

    def __init__(self):
        from transformers import AutoTokenizer
        from ctranslate2._ext import Translator
        self.tokenizer = AutoTokenizer.from_pretrained(self.MODEL_NAME)
        self.translator = Translator(
            self.MODEL_DIR, device="cpu", compute_type="int8",
            inter_threads=1, intra_threads=4
        )

    def translate(self, text, src_lang="eng_Latn", tgt_lang="tur_Latn"):
        if not text.strip():
            return ""
        self.tokenizer.src_lang = src_lang
        ids = self.tokenizer.encode(text, truncation=True, max_length=256)
        source = self.tokenizer.convert_ids_to_tokens(ids)
        results = self.translator.translate_batch(
            [source], target_prefix=[[tgt_lang]], beam_size=1,
            max_decoding_length=160, repetition_penalty=1.15, disable_unk=True
        )
        if not results:
            return ""
        tokens = results[0].hypotheses[0]
        if tokens and tokens[0] == tgt_lang:
            tokens = tokens[1:]
        return self.tokenizer.decode(
            self.tokenizer.convert_tokens_to_ids(tokens),
            skip_special_tokens=True
        ).strip()

    def clean_text(self, text):
        import re
        # Emoji ve ozel AI isaretlerini temizle
        text = re.sub(r'[^\x00-\x7F\xc0-\xff\u0100-\u017f]+', '', text)
        text = re.sub(r'\[.*?\]|\(.*?\)', '', text)
        return text.strip()


class OverlayWindow(QWidget):
    def __init__(self, x=100, y=60, w=800):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(x, y, w, 100)
        self.label = QLabel("Hazirlaniyor...", self)
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.label.setWordWrap(True)
        self.label.setMinimumWidth(w)
        self.label.setMaximumWidth(w)
        self.label.setFont(QFont("Segoe UI", 16, QFont.Bold))
        self.label.setStyleSheet(
            "QLabel{color:white;background-color:rgba(13,17,23,220);"
            "border:2px solid rgba(88,166,255,180);border-radius:12px;padding:14px;}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)

    def showEvent(self, event):
        super().showEvent(event)
        hwnd = int(self.winId())
        SetWindowLongW(hwnd, GWL_EXSTYLE,
                       GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW)

    def set_text(self, text):
        if text.strip():
            self.label.setText(text)
            self.adjustSize()


class ModelLoaderThread(QThread):
    finished = pyqtSignal(object, object)
    status = pyqtSignal(str, int)

    def __init__(self, whisper_model):
        super().__init__()
        self.whisper_model = whisper_model

    def run(self):
        try:
            self.status.emit("Whisper yukleniyor...", 45)
            speech = SpeechEngine(self.whisper_model)
            self.status.emit("Ceviri modeli yukleniyor...", 85)
            translator = TranslationEngine()
            self.status.emit("Hazir", 100)
            gc.collect()
            self.finished.emit(speech, translator)
        except Exception as e:
            print(e)
            self.status.emit(f"Hata: {e}", 0)
            self.finished.emit(None, None)


class AudioWorker(QThread):
    ENGINE_LOCK = threading.Lock()
    result_ready = pyqtSignal(str, str)
    transcription_ready = pyqtSignal(str)
    error_ready = pyqtSignal(str)

    def __init__(self, speech, translator, audio, speech_lang, src_lang, tgt_lang):
        super().__init__()
        self.speech = speech
        self.translator = translator
        self.audio = audio
        self.speech_lang = speech_lang
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang

    def run(self):
        try:
            with self.ENGINE_LOCK:
                text = self.speech.transcribe(self.audio, self.speech_lang)
                if not text:
                    return
                self.transcription_ready.emit(text)
                translated = self.translator.translate(text, self.src_lang, self.tgt_lang)
            if translated:
                self.result_ready.emit(text, translated)
        except Exception as e:
            self.error_ready.emit(str(e))
        finally:
            self.audio = None


class ControlPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SoileTranslate Ses")
        self.setMinimumSize(620, 580)
        self.resize(660, 620)
        self.setStyleSheet(DARK_STYLE)
        self.speech = None
        self.translator = None
        self.audio_capture = None
        self.mic_capture = None
        self.audio_overlay = None
        self.mic_overlay = None
        self._audio_running = False
        self._mic_running = False
        self._audio_translating = False
        self._mic_translating = False
        self._pending_start = None
        self._mic_recording = False
        self._kb_available = True
        self.history = []
        self.workers = []
        self._init_ui()
        self.audio_timer = QTimer()
        self.audio_timer.timeout.connect(self._audio_tick)
        self.mic_timer = QTimer()
        self.mic_timer.timeout.connect(self._mic_tick)
        self._refresh_devices()
        # keyboard modülünü önceden yükle
        try:
            import keyboard
            self._kb = keyboard
        except Exception:
            self._kb = None
            self._kb_available = False

    def _init_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(16, 14, 16, 14)
        main.setSpacing(10)

        # Başlık
        title = QLabel("SoileTranslate Ses")
        title.setObjectName("titleLabel")
        title.setAlignment(Qt.AlignCenter)
        main.addWidget(title)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#30363d;")
        main.addWidget(line)

        # İki panel yan yana
        content = QHBoxLayout()
        content.setSpacing(12)
        main.addLayout(content, 1)

        # ── Sol: PC Sesi ──
        ag = QGroupBox("🔊 PC Sesi  EN → TR")
        al = QVBoxLayout(ag)
        al.setContentsMargins(14, 20, 14, 14)
        al.setSpacing(8)

        self.whisper_combo = QComboBox()
        self.whisper_combo.addItems(["tiny", "base", "small"])
        self.whisper_combo.setCurrentText("base")
        self.whisper_combo.setMinimumHeight(32)
        al.addWidget(QLabel("Whisper modeli:"))
        al.addWidget(self.whisper_combo)

        self.audio_dev_combo = QComboBox()
        self.audio_dev_combo.setMinimumHeight(32)
        al.addWidget(QLabel("PC ses cikisi:"))
        al.addWidget(self.audio_dev_combo)

        self.audio_state = QLabel("● Kapali")
        self.audio_state.setObjectName("stateLabel")
        al.addWidget(self.audio_state)

        row = QHBoxLayout()
        self.btn_audio_start = QPushButton("▶ Baslat")
        self.btn_audio_start.setObjectName("btnStart")
        self.btn_audio_start.clicked.connect(self._start_audio)
        self.btn_audio_stop = QPushButton("■ Durdur")
        self.btn_audio_stop.setObjectName("btnStop")
        self.btn_audio_stop.setEnabled(False)
        self.btn_audio_stop.clicked.connect(self._stop_audio)
        row.addWidget(self.btn_audio_start)
        row.addWidget(self.btn_audio_stop)
        al.addLayout(row)
        al.addStretch()
        content.addWidget(ag)

        # ── Sağ: Mikrofon ──
        mg = QGroupBox("🎤 Mikrofon  TR → EN")
        ml = QVBoxLayout(mg)
        ml.setContentsMargins(14, 20, 14, 14)
        ml.setSpacing(8)

        self.hotkey_combo = QComboBox()
        self.hotkey_combo.addItems(["v", "b", "alt", "ctrl", "shift", "caps lock", "space"])
        self.hotkey_combo.setMinimumHeight(32)
        ml.addWidget(QLabel("Bas-konus tusu:"))
        ml.addWidget(self.hotkey_combo)

        self.mic_dev_combo = QComboBox()
        self.mic_dev_combo.setMinimumHeight(32)
        ml.addWidget(QLabel("Mikrofon:"))
        ml.addWidget(self.mic_dev_combo)

        self.mic_state = QLabel("● Kapali")
        self.mic_state.setObjectName("stateLabel")
        ml.addWidget(self.mic_state)

        row = QHBoxLayout()
        self.btn_mic_start = QPushButton("▶ Baslat")
        self.btn_mic_start.setObjectName("btnStart")
        self.btn_mic_start.clicked.connect(self._start_mic)
        self.btn_mic_stop = QPushButton("■ Durdur")
        self.btn_mic_stop.setObjectName("btnStop")
        self.btn_mic_stop.setEnabled(False)
        self.btn_mic_stop.clicked.connect(self._stop_mic)
        row.addWidget(self.btn_mic_start)
        row.addWidget(self.btn_mic_stop)
        ml.addLayout(row)
        ml.addStretch()
        content.addWidget(mg)

        # ── İkisi Birlikte Butonları ──
        both_row = QHBoxLayout()
        both_row.setSpacing(10)
        self.btn_both_start = QPushButton("⏩ Ikisini Birden Baslat")
        self.btn_both_start.setObjectName("btnBoth")
        self.btn_both_start.setMinimumHeight(40)
        self.btn_both_start.clicked.connect(self._start_both)
        self.btn_all_stop = QPushButton("Durdur")
        self.btn_all_stop.setObjectName("btnStop")
        self.btn_all_stop.setMinimumHeight(40)
        self.btn_all_stop.clicked.connect(self._stop_all)
        both_row.addWidget(self.btn_both_start)
        both_row.addWidget(self.btn_all_stop)
        main.addLayout(both_row)

        # ── Durum Paneli ──
        sg = QGroupBox("Durum")
        sl = QVBoxLayout(sg)
        sl.setContentsMargins(14, 18, 14, 14)
        sl.setSpacing(6)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setMaximumHeight(18)
        self.status_label = QLabel("Hazir")
        self.log_label = QLabel("")
        self.log_label.setObjectName("logLabel")
        self.log_label.setMinimumHeight(70)
        self.log_label.setWordWrap(True)
        sl.addWidget(self.progress)
        sl.addWidget(self.status_label)
        sl.addWidget(self.log_label)
        main.addWidget(sg)

    # ── Yardımcılar ──

    def _log(self, msg):
        lines = self.log_label.text().split("\n")
        lines.append(msg)
        self.log_label.setText("\n".join(lines[-3:]))

    def _refresh_devices(self):
        try:
            import soundcard as sc
            import sounddevice as sd
        except Exception as e:
            self._log(f"Cihaz yenilemesi hatasi: {e}")
            return
        self.audio_dev_combo.clear()
        self.audio_dev_combo.addItem("Otomatik", ("soundcard", None))
        try:
            for i, speaker in enumerate(sc.all_speakers()):
                self.audio_dev_combo.addItem(f"PC SESI: {speaker.name}", ("soundcard", i))
        except Exception:
            pass
        self.mic_dev_combo.clear()
        self.mic_dev_combo.addItem("Varsayilan Mikrofon", -1)
        try:
            devices = sd.query_devices()
            has_wasapi = any(
                d["max_input_channels"] > 0
                and sd.query_hostapis(d["hostapi"])["name"] == "Windows WASAPI"
                and ("mikrofon" in d["name"].lower() or "microphone" in d["name"].lower())
                for d in devices
            )
            for i, d in enumerate(devices):
                name = d["name"]
                lower = name.lower()
                hostapi = sd.query_hostapis(d["hostapi"])["name"]
                is_mic = ("mikrofon" in lower or "microphone" in lower or
                          ("mic" in lower and "microsoft" not in lower))
                if d["max_input_channels"] > 0 and is_mic and "stereo mix" not in lower:
                    if has_wasapi and hostapi != "Windows WASAPI":
                        continue
                    self.mic_dev_combo.addItem(f"{name} ({hostapi})", i)
        except Exception:
            pass

    # ── Model Yükleme ──

    def _ensure_models(self, after_load):
        self._pending_start = after_load
        self.btn_audio_start.setEnabled(False)
        self.btn_mic_start.setEnabled(False)
        self.btn_both_start.setEnabled(False)
        if self.speech and self.translator:
            self._pending_start = None
            after_load()
            self._sync_buttons()
            return
        self.progress.setVisible(True)
        self.status_label.setText("Modeller yukleniyor...")
        self.loader = ModelLoaderThread(self.whisper_combo.currentText())
        self.loader.status.connect(
            lambda m, p: (self._log(m), self.progress.setValue(p), self.status_label.setText(m))
        )
        self.loader.finished.connect(self._models_ready)
        self.loader.start()

    def _models_ready(self, speech, translator):
        self.progress.setVisible(False)
        if not speech or not translator:
            self.status_label.setText("Model hatasi")
            self._log("Model yuklenemedi.")
            self._sync_buttons()
            return
        self.speech = speech
        self.translator = translator
        pending = self._pending_start
        self._pending_start = None
        if pending:
            pending()
        self._sync_buttons()

    # ── Başlatma ──

    def _start_audio(self):
        self._ensure_models(self._begin_audio)

    def _start_mic(self):
        self._ensure_models(self._begin_mic)

    def _start_both(self):
        self._ensure_models(lambda: (self._begin_audio(), self._begin_mic()))

    def _begin_audio(self):
        if self._audio_running:
            return
        scr = QApplication.primaryScreen().geometry()
        try:
            self.history = []
            idx = self.audio_dev_combo.currentData()
            self.audio_capture = AudioCapture(idx)
            self.audio_capture.start()
            self.audio_overlay = OverlayWindow((scr.width() - 800) // 2, 60, 800)
            self.audio_overlay.set_text("PC sesi dinleniyor...")
            self.audio_overlay.show()
            self._audio_running = True
            self.audio_state.setText("● Hazir")
            self.audio_state.setObjectName("stateActive")
            self.audio_state.setStyleSheet(self.styleSheet())
            self.status_label.setText("PC sesi aktif")
            self.audio_timer.start(300)
        except Exception as e:
            self._log(f"PC sesi baslatilamadi: {e}")
            self._stop_audio()
        self._sync_buttons()

    def _begin_mic(self):
        if self._mic_running:
            return
        if not self._kb_available or self._kb is None:
            self._log("keyboard modulu yuklenemedi!")
            return
        scr = QApplication.primaryScreen().geometry()
        try:
            idx = self.mic_dev_combo.currentData()
            self.mic_capture = MicrophoneCapture(None if idx == -1 else idx)
            self.mic_overlay = OverlayWindow((scr.width() - 800) // 2, scr.height() - 180, 800)
            key = self.hotkey_combo.currentText().upper()
            self.mic_overlay.set_text(f"[{key}] basili tutarak konus.")
            self.mic_overlay.show()
            self._mic_running = True
            self.mic_state.setText(f"● [{key}] bekleniyor")
            self.mic_state.setObjectName("stateActive")
            self.mic_state.setStyleSheet(self.styleSheet())
            self.status_label.setText("Mikrofon aktif")
            self.mic_timer.start(50)
        except Exception as e:
            self._log(f"Mikrofon baslatilamadi: {e}")
            self._stop_mic()
        self._sync_buttons()

    # ── Timer Tick'leri ──

    def _audio_tick(self):
        if not self._audio_running or self._audio_translating or not self.audio_capture:
            return
        try:
            if self.audio_capture._record_error:
                self._log(str(self.audio_capture._record_error))
                self._stop_audio()
                return
            chunk = self.audio_capture.get_chunk()
            if chunk is not None and float(np.sqrt(np.mean(chunk ** 2))) > 0.0022:
                self.audio_state.setText("🔄 Cevriliyor")
                self._run_worker("audio", chunk, "en", "eng_Latn", "tur_Latn")
        except Exception as e:
            self._log(f"Ses hatasi: {e}")

    def _mic_tick(self):
        if not self._mic_running or self._mic_translating or not self.mic_capture:
            return
        try:
            key = self.hotkey_combo.currentText()
            pressed = self._kb.is_pressed(key)
        except Exception:
            # keyboard erişim hatası — çökmeyi önle
            return
        try:
            if pressed and not self._mic_recording:
                self._mic_recording = True
                self.mic_state.setText("● Konusuyor...")
                self.mic_state.setObjectName("stateRecording")
                self.mic_state.setStyleSheet(self.styleSheet())
                if self.mic_overlay:
                    self.mic_overlay.set_text("🎤 Konusuyor...")
                try:
                    self.mic_capture.start()
                except Exception as e:
                    self._log(f"Mikrofon acilamadi: {e}")
                    self._mic_recording = False
                    return
            elif not pressed and self._mic_recording:
                self._mic_recording = False
                try:
                    audio = self.mic_capture.stop()
                except Exception as e:
                    self._log(f"Mikrofon kapatilamadi: {e}")
                    audio = None
                if audio is not None and len(audio) > 16000 * 0.3:
                    self.mic_state.setText("● Isleniyor...")
                    if self.mic_overlay:
                        self.mic_overlay.set_text("Cevriliyor...")
                    self._run_worker("mic", audio, "tr", "tur_Latn", "eng_Latn")
                else:
                    self.mic_state.setText(f"🟡 [{key.upper()}] bekleniyor")
                    if self.mic_overlay:
                        self.mic_overlay.set_text(f"[{key.upper()}] basili tutarak konus.")
        except Exception as e:
            self._log(f"Mikrofon hatasi: {e}")

    # ── Çeviri Worker ──

    def _run_worker(self, source, audio, speech_lang, src_lang, tgt_lang):
        if source == "audio":
            self._audio_translating = True
        else:
            self._mic_translating = True
        worker = AudioWorker(self.speech, self.translator, audio, speech_lang, src_lang, tgt_lang)
        worker.transcription_ready.connect(lambda t: self._log(t[:70]))
        worker.result_ready.connect(lambda src, tr: self._on_translated(source, src, tr))
        worker.error_ready.connect(lambda e: self._log(f"Hata: {e}"))
        worker.finished.connect(lambda s=source, w=worker: self._worker_finished(s, w))
        self.workers.append(worker)
        worker.start()

    def _worker_finished(self, source, worker):
        if source == "audio":
            self._audio_translating = False
            if self._audio_running:
                self.audio_state.setText("🟢 Dinleniyor")
        else:
            self._mic_translating = False
            if self._mic_running:
                key = self.hotkey_combo.currentText().upper()
                self.mic_state.setText(f"🟡 [{key}] bekleniyor")
                # Overlay metnini hemen sifirlama, kullanici ceviri gorsun
        if worker in self.workers:
            self.workers.remove(worker)
        # Temizlik
        gc.collect()

    def _on_translated(self, source, src, tr):
        # Emojileri ve gereksiz AI isaretlerini temizle
        tr = self.translator.clean_text(tr)
        if not tr: return
        
        if source == "audio":
            self.history = (self.history + [" ".join(tr.split())])[-4:]
            if self.audio_overlay:
                self.audio_overlay.set_text("\n\n".join(self.history))
        else:
            if self.mic_overlay:
                self.mic_overlay.set_text(tr)
        self._log(tr[:70])

    # ── Durdurma ──

    def _stop_audio(self):
        self._audio_running = False
        self.audio_timer.stop()
        if self.audio_capture:
            self.audio_capture.stop()
            self.audio_capture = None
        if self.audio_overlay:
            self.audio_overlay.close()
            self.audio_overlay = None
        self.audio_state.setText("● Kapali")
        self.audio_state.setObjectName("stateLabel")
        self.audio_state.setStyleSheet(self.styleSheet())
        self.status_label.setText("PC sesi durduruldu")
        self._sync_buttons()

    def _stop_mic(self):
        self._mic_running = False
        self._mic_recording = False
        self.mic_timer.stop()
        if self.mic_capture:
            try:
                self.mic_capture.stop()
            except Exception:
                pass
            self.mic_capture = None
        if self.mic_overlay:
            self.mic_overlay.close()
            self.mic_overlay = None
        self.mic_state.setText("● Kapali")
        self.mic_state.setObjectName("stateLabel")
        self.mic_state.setStyleSheet(self.styleSheet())
        self.status_label.setText("Mikrofon durduruldu")
        self._sync_buttons()

    def _stop_all(self):
        self._stop_audio()
        self._stop_mic()
        self.status_label.setText("Durduruldu")

    def _sync_buttons(self):
        loading = bool(getattr(self, "loader", None) and self.loader.isRunning())
        self.btn_audio_start.setEnabled(not loading and not self._audio_running)
        self.btn_mic_start.setEnabled(not loading and not self._mic_running)
        self.btn_both_start.setEnabled(not loading and (not self._audio_running or not self._mic_running))
        self.btn_audio_stop.setEnabled(self._audio_running)
        self.btn_mic_stop.setEnabled(self._mic_running)

    def closeEvent(self, event):
        self._stop_all()
        super().closeEvent(event)


class App:
    def __init__(self):
        self.qapp = QApplication(sys.argv)
        self.qapp.setStyle("Fusion")
        px = QPixmap(32, 32)
        px.fill(QColor("#58a6ff"))
        icon = QIcon(px)
        self.qapp.setWindowIcon(icon)
        self.panel = ControlPanel()
        self.tray = QSystemTrayIcon(icon, self.qapp)
        menu = QMenu()
        show = QAction("Paneli Goster", menu)
        show.triggered.connect(lambda: self.panel.show() or self.panel.raise_())
        quit_action = QAction("Cikis", menu)
        quit_action.triggered.connect(lambda: self.panel._stop_all() or self.qapp.quit())
        menu.addAction(show)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def run(self):
        self.panel.show()
        sys.exit(self.qapp.exec_())


if __name__ == "__main__":
    App().run()
