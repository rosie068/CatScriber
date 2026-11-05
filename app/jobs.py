"""In-memory job tracking. Single-user local app — no DB needed."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal, Optional

Stage = Literal[
    "queued",
    "transcribing",
    "charting",
    "emailing",
    "done",
    "error",
]


@dataclass
class Job:
    id: str
    patient_name: str
    visit_date: str
    recipient: str
    audio_path: str
    stage: Stage = "queued"
    progress: float = 0.0  # 0..1, only meaningful during `transcribing`
    message: str = ""
    error: Optional[str] = None
    transcript: Optional[str] = None
    chart: Optional[str] = None
    detected_language: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, *, patient_name: str, visit_date: str, recipient: str, audio_path: str) -> Job:
        job = Job(
            id=uuid.uuid4().hex,
            patient_name=patient_name,
            visit_date=visit_date,
            recipient=recipient,
            audio_path=audio_path,
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for k, v in fields.items():
                setattr(job, k, v)
            job.updated_at = time.time()


store = JobStore()
