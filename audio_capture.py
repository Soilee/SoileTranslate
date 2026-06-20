import threading
import time
import ctypes
import numpy as np

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
