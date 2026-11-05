"""Cat_Scriber — FastAPI app.

Single-user local web app:
1. Drag-drop audio file + patient name + recipient email.
2. Server saves to ./uploads/<job_id>/ and runs transcription -> charting -> email
   on a background thread.
3. UI polls /jobs/{id} until done. On done, transcript and chart are shown
   inline (and also delivered by email).
4. With PURGE_AFTER_SEND=true, on-disk files are deleted once the email is sent.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import traceback
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()

from app import chart as chart_mod  # noqa: E402
from app import email_send  # noqa: E402
from app import transcribe as transcribe_mod  # noqa: E402
from app.jobs import store  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("cat_scriber")

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "uploads"
UPLOADS.mkdir(exist_ok=True)

app = FastAPI(title="Cat_Scriber")
app.mount("/static", StaticFiles(directory=str(ROOT / "app" / "static")), name="static")
templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))


@app.on_event("startup")
def _prewarm_whisper() -> None:
    backend = transcribe_mod.active_backend()
    log.info("Pre-warming Whisper backend=%s ...", backend)
    threading.Thread(target=transcribe_mod.prewarm, daemon=True).start()

ALLOWED_EXTS = {".mp3", ".m4a", ".wav", ".mp4", ".mov", ".aac", ".flac", ".ogg", ".webm", ".opus"}
MAX_BYTES = 500 * 1024 * 1024  # 500 MB — generous for ~1hr at high bitrates


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "default_recipient": os.environ.get("DEFAULT_RECIPIENT", ""),
            "today": date.today().isoformat(),
        },
    )


@app.post("/upload")
async def upload(
    audio: UploadFile,
    patient_name: str = Form(...),
    visit_date: str = Form(...),
    recipient: str = Form(...),
) -> JSONResponse:
    if not audio.filename:
        raise HTTPException(400, "No file provided.")
    ext = Path(audio.filename).suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"Unsupported file type {ext}. Allowed: {sorted(ALLOWED_EXTS)}")

    patient_name = patient_name.strip()
    visit_date = visit_date.strip()
    recipient = recipient.strip()
    if not patient_name or not visit_date or not recipient:
        raise HTTPException(400, "patient_name, visit_date, and recipient are required.")

    job = store.create(
        patient_name=patient_name,
        visit_date=visit_date,
        recipient=recipient,
        audio_path="",  # filled below
    )

    job_dir = UPLOADS / job.id
    job_dir.mkdir(parents=True, exist_ok=True)
    audio_path = job_dir / f"audio{ext}"

    bytes_written = 0
    with audio_path.open("wb") as f:
        while True:
            chunk = await audio.read(1024 * 1024)
            if not chunk:
                break
            bytes_written += len(chunk)
            if bytes_written > MAX_BYTES:
                f.close()
                shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(413, f"File exceeds {MAX_BYTES // (1024*1024)} MB limit.")
            f.write(chunk)

    store.update(job.id, audio_path=str(audio_path))

    threading.Thread(target=_run_pipeline, args=(job.id,), daemon=True).start()

    return JSONResponse({"job_id": job.id})


@app.get("/jobs/{job_id}")
async def job_status(job_id: str) -> JSONResponse:
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "Unknown job.")
    return JSONResponse(
        {
            "id": job.id,
            "stage": job.stage,
            "progress": round(job.progress, 3),
            "message": job.message,
            "error": job.error,
            "patient_name": job.patient_name,
            "visit_date": job.visit_date,
            "detected_language": job.detected_language,
            "transcript": job.transcript,
            "chart": job.chart,
        }
    )


def _run_pipeline(job_id: str) -> None:
    job = store.get(job_id)
    if not job:
        return
    audio_path = Path(job.audio_path)
    job_dir = audio_path.parent

    try:
        # 1. Transcribe
        store.update(job_id, stage="transcribing", progress=0.0, message="Transcribing audio (this can take a while on CPU)...")
        log.info("[%s] transcribing %s", job_id, audio_path)

        def on_progress(p: float) -> None:
            store.update(job_id, progress=p)

        result = transcribe_mod.transcribe(audio_path, progress=on_progress)
        log.info(
            "[%s] transcribed %.1fs of audio in %.1fs (lang=%s, %d chars)",
            job_id,
            result.duration_seconds,
            result.elapsed_seconds,
            result.detected_language,
            len(result.text),
        )
        store.update(
            job_id,
            transcript=result.text,
            detected_language=result.detected_language,
            progress=1.0,
        )

        if not result.text.strip():
            raise RuntimeError("Transcription produced no text. Check the audio file.")

        # 2. Chart
        store.update(job_id, stage="charting", message="Generating chart with Claude...")
        log.info("[%s] charting", job_id)
        chart = chart_mod.generate_chart(
            transcript=result.text,
            patient_name=job.patient_name,
            visit_date=job.visit_date,
        )
        log.info(
            "[%s] chart generated (in=%d out=%d cache_read=%d cache_creation=%d)",
            job_id,
            chart.input_tokens,
            chart.output_tokens,
            chart.cache_read_tokens,
            chart.cache_creation_tokens,
        )
        store.update(job_id, chart=chart.text)

        # 3. Email
        store.update(job_id, stage="emailing", message="Sending email...")
        log.info("[%s] emailing %s", job_id, job.recipient)
        email_send.send_chart_email(
            recipient=job.recipient,
            patient_name=job.patient_name,
            visit_date=job.visit_date,
            transcript_text=result.text,
            chart_text=chart.text,
            detected_language=result.detected_language,
        )

        store.update(job_id, stage="done", message=f"Done — emailed to {job.recipient}.")
        log.info("[%s] done", job_id)

    except Exception as e:  # noqa: BLE001
        log.error("[%s] pipeline failed: %s\n%s", job_id, e, traceback.format_exc())
        store.update(job_id, stage="error", error=str(e), message=f"Failed: {e}")

    finally:
        if os.environ.get("PURGE_AFTER_SEND", "true").lower() == "true":
            current = store.get(job_id)
            if current and current.stage == "done":
                shutil.rmtree(job_dir, ignore_errors=True)
                log.info("[%s] purged %s", job_id, job_dir)
