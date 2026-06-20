import os
import numpy as np

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
