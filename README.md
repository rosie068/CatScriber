# Cat_Scriber

Local web app that turns ~1hr dental visit recordings into an EMR-ready chart note, emailed to you.

- **Audio stays on your machine.** Whisper runs locally; the audio file never leaves your computer.
- **Chart generation uses Claude** (Anthropic API). Only the transcript text is sent.
- **Bilingual.** Handles English + Mandarin code-switching natively (Whisper auto-detects per chunk; chart is output in clinical English).
- **Auto-deletes** uploaded audio + transcript on disk after the email is sent.

> ⚠️ **Clinical use disclaimer.** Always review the generated chart for accuracy before pasting into the EMR. Whisper occasionally mis-hears tooth numbers and dental terminology, especially in noisy operatory audio. The chart prompt asks Claude to flag uncertain items under "Notes / clarifications needed" — read that section every time.

## Setup (one-time)

### 1. Install Python 3.10+ and ffmpeg

ffmpeg is required by Whisper to decode m4a/mp4/etc.

**macOS (Homebrew):**
```bash
brew install python ffmpeg
```

**Windows:** install Python from python.org, and ffmpeg from <https://www.gyan.dev/ffmpeg/builds/> (add to PATH).

### 2. Configure `.env`

```bash
cp .env.example .env
```

Open `.env` and fill in:

- `ANTHROPIC_API_KEY` — get one at <https://console.anthropic.com/>
- `SMTP_*` — for Gmail:
  1. Enable 2-Step Verification on your Google account.
  2. Create an App Password: <https://myaccount.google.com/apppasswords>.
  3. Put the 16-character app password (not your Gmail password) in `SMTP_PASSWORD`.
- `DEFAULT_RECIPIENT` — the email address that should receive transcripts + charts (your sister's address).

### 3. First-time launch

```bash
./run.sh
```

This creates a virtualenv, installs dependencies, and starts the server at <http://127.0.0.1:8000>. The first time you transcribe anything, faster-whisper will download the model (~1.5 GB for `medium`). Subsequent runs reuse the cached model.

## Daily use

1. Run `./run.sh`.
2. Open <http://127.0.0.1:8000>.
3. Fill in patient name, visit date, recipient email, and drop the audio file in.
4. Wait. On an Intel Mac with the `medium` model, expect roughly **30–45 minutes per hour of audio** (CPU-bound). Apple Silicon Macs are 3–5× faster.
5. When done, the chart and transcript appear in the page and arrive in the recipient's inbox.

## Tuning

In `.env`:

- `WHISPER_MODEL=small` — ~3× faster, slightly lower Mandarin accuracy. Good if waits are too long.
- `WHISPER_MODEL=large-v3` — best Mandarin accuracy, but very slow on CPU (multi-hour for 1hr audio). Only use if you have a CUDA GPU.
- `CHART_MODEL=claude-opus-4-7` — higher chart quality, more expensive than Sonnet.
- `PURGE_AFTER_SEND=false` — keep audio + transcript files in `./uploads/<job_id>/` for debugging. Default is `true`.

## Editing the chart format

The chart prompt lives in `prompts/dental_chart.md`. It's a plain Markdown file — edit it to match the EMR template, change section headers, add or remove fields, etc. Changes take effect on the next chart (no restart needed; it's read fresh each call).

## Privacy notes

- Audio file: stored at `./uploads/<job_id>/audio.<ext>` only while transcription is running. Deleted after email send (when `PURGE_AFTER_SEND=true`).
- Transcript text: held in memory + sent to Anthropic's API for charting + included in the outbound email. Never written to disk in plaintext beyond the outbound `.eml` (held momentarily by your SMTP server).
- Anthropic does not train on API data. For zero-retention API access, contact Anthropic to enable it on your account.
- Email transport: standard SMTP+STARTTLS. Both Gmail and the recipient's mail server may retain the message indefinitely. If you need stronger guarantees, use end-to-end encrypted email (e.g. ProtonMail) or skip email and read the transcript/chart from the browser only.

## Troubleshooting

- **`ANTHROPIC_API_KEY is not set`** — `./run.sh` couldn't find your key. Check `.env` is in the project root and is named exactly `.env`.
- **`SMTP not configured`** — same, but for SMTP fields. Gmail specifically needs an App Password, not the regular password.
- **Whisper says "no module named faster_whisper"** — delete `.venv/` and re-run `./run.sh`.
- **Transcription is empty** — usually means the audio file is silent or in a format ffmpeg can't decode. Confirm ffmpeg is installed (`ffmpeg -version`).
- **"Unsupported file type"** — convert to mp3/m4a/wav. iPhone Voice Memos exports `.m4a` by default which works directly.

## File layout

```
Cat_Scriber/
├── app/
│   ├── main.py            FastAPI app + background pipeline
│   ├── transcribe.py      faster-whisper wrapper
│   ├── chart.py           Anthropic API call
│   ├── email_send.py      SMTP delivery
│   ├── jobs.py            in-memory job tracking
│   ├── templates/
│   │   └── index.html     upload UI
│   └── static/
│       ├── app.js         drag-drop + status polling
│       └── styles.css
├── prompts/
│   └── dental_chart.md    chart prompt (edit this to change format)
├── uploads/               runtime storage, auto-purged
├── requirements.txt
├── run.sh                 one-shot launcher
├── .env.example
└── .gitignore
```
