import threading
import gc
from PyQt5.QtCore import QThread, pyqtSignal
from ai_engines import SpeechEngine, TranslationEngine

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
