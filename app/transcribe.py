"""Local audio transcription with pluggable backends.

Two backends are supported, selected by `WHISPER_BACKEND`:
  - "mlx"          — Apple MLX, fast on Apple Silicon (Neural Engine + Metal).
                     Recommended on M-series Macs.
  - "ctranslate2"  — faster-whisper / CTranslate2 int8, runs on any CPU.
                     Fallback for Intel Macs and other platforms.

If `WHISPER_BACKEND` is unset or "auto", we pick MLX when running on
Apple Silicon and the package imports successfully, else CT2.

The active backend's model is pre-loaded at server startup via `prewarm()`
so the first transcription doesn't pay a cold-start penalty.
"""

from __future__ import annotations

import os
import platform
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


@dataclass
class TranscriptionResult:
    text: str
    detected_language: str
    duration_seconds: float
    elapsed_seconds: float


_backend_lock = threading.Lock()
_resolved_backend: Optional[str] = None


def _resolve_backend() -> str:
    global _resolved_backend
    with _backend_lock:
        if _resolved_backend is not None:
            return _resolved_backend

        explicit = os.environ.get("WHISPER_BACKEND", "auto").strip().lower()
        if explicit in {"mlx", "ctranslate2"}:
            _resolved_backend = explicit
            return _resolved_backend

        # auto: prefer MLX on Apple Silicon when the package is importable
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            try:
                import mlx_whisper  # noqa: F401

                _resolved_backend = "mlx"
                return _resolved_backend
            except ImportError:
                pass
        _resolved_backend = "ctranslate2"
        return _resolved_backend


# ---------- MLX backend ----------

_mlx_model_loaded = False
_mlx_lock = threading.Lock()


def _mlx_repo() -> str:
    # Override via WHISPER_MODEL=mlx-community/whisper-large-v3-turbo for the distilled variant.
    return os.environ.get("WHISPER_MODEL", "mlx-community/whisper-large-v3-mlx")


def _mlx_prewarm() -> None:
    """Force model download + first-run JIT compile so the first transcription
    request doesn't include a cold-start.

    mlx-whisper caches the loaded model after the first transcribe() call. A
    single short-buffer call is the simplest way to trigger that load.
    """
    global _mlx_model_loaded
    with _mlx_lock:
        if _mlx_model_loaded:
            return
        import mlx_whisper
        import numpy as np

        # 1 second of silence at 16 kHz — minimal valid input
        silence = np.zeros(16000, dtype=np.float32)
        mlx_whisper.transcribe(
            silence,
            path_or_hf_repo=_mlx_repo(),
            verbose=False,
            fp16=True,
        )
        _mlx_model_loaded = True


def _mlx_transcribe(audio_path: Path, progress: Optional[Callable[[float], None]]) -> TranscriptionResult:
    import mlx_whisper
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import collect_chunks, get_speech_timestamps

    started = time.monotonic()
    if progress:
        progress(0.05)

    # Pre-filter silence with Silero VAD before sending to mlx-whisper. Long
    # quiet stretches otherwise trigger the well-known repetition-loop
    # hallucination in Whisper. mlx-whisper has no native VAD; faster-whisper
    # ships Silero, which we reuse here. Audio is decoded to 16 kHz mono
    # float32 — the format both VAD and mlx-whisper expect.
    audio = decode_audio(str(audio_path), sampling_rate=16000)
    original_duration = len(audio) / 16000.0
    speech_chunks = get_speech_timestamps(audio)
    audio_for_asr = collect_chunks(audio, speech_chunks) if speech_chunks else audio

    if progress:
        progress(0.1)

    result = mlx_whisper.transcribe(
        audio_for_asr,
        path_or_hf_repo=_mlx_repo(),
        verbose=False,
        fp16=True,
        condition_on_previous_text=True,
    )

    if progress:
        progress(1.0)

    text = (result.get("text") or "").strip()
    language = result.get("language") or "unknown"

    return TranscriptionResult(
        text=text,
        detected_language=language,
        duration_seconds=original_duration,
        elapsed_seconds=time.monotonic() - started,
    )


# ---------- CTranslate2 (faster-whisper) backend ----------

_ct2_model = None  # type: ignore[var-annotated]
_ct2_lock = threading.Lock()


def _ct2_get_model():
    global _ct2_model
    with _ct2_lock:
        if _ct2_model is None:
            from faster_whisper import WhisperModel

            model_size = os.environ.get("WHISPER_MODEL", "medium")
            compute_type = os.environ.get("WHISPER_COMPUTE", "int8")
            threads_env = os.environ.get("WHISPER_THREADS", "0")
            try:
                threads = int(threads_env)
            except ValueError:
                threads = 0

            kwargs: dict = {"device": "cpu", "compute_type": compute_type}
            if threads > 0:
                kwargs["cpu_threads"] = threads
            _ct2_model = WhisperModel(model_size, **kwargs)
    return _ct2_model


def _ct2_transcribe(audio_path: Path, progress: Optional[Callable[[float], None]]) -> TranscriptionResult:
    model = _ct2_get_model()
    started = time.monotonic()

    segments_iter, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=True,
    )

    total = info.duration or 0.0
    chunks: list[str] = []
    for seg in segments_iter:
        chunks.append(seg.text)
        if progress and total > 0:
            progress(min(1.0, seg.end / total))

    text = "".join(chunks).strip()
    if progress:
        progress(1.0)

    return TranscriptionResult(
        text=text,
        detected_language=info.language,
        duration_seconds=total,
        elapsed_seconds=time.monotonic() - started,
    )


# ---------- Public API ----------


def active_backend() -> str:
    return _resolve_backend()


def prewarm() -> None:
    """Eager model load. Call once at server startup."""
    backend = _resolve_backend()
    if backend == "mlx":
        _mlx_prewarm()
    else:
        _ct2_get_model()


def transcribe(
    audio_path: Path,
    progress: Optional[Callable[[float], None]] = None,
) -> TranscriptionResult:
    backend = _resolve_backend()
    if backend == "mlx":
        return _mlx_transcribe(audio_path, progress)
    return _ct2_transcribe(audio_path, progress)
