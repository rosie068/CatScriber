"""SMTP email delivery with text attachments.

Uses STARTTLS on port 587 by default. For Gmail, the user must generate an
App Password (https://myaccount.google.com/apppasswords) — regular Gmail
passwords no longer work for SMTP.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

import certifi


def send_chart_email(
    *,
    recipient: str,
    patient_name: str,
    visit_date: str,
    transcript_text: str,
    chart_text: str,
    detected_language: str,
) -> None:
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    sender = os.environ.get("SMTP_FROM") or user

    missing = [
        name
        for name, val in [
            ("SMTP_HOST", host),
            ("SMTP_USER", user),
            ("SMTP_PASSWORD", password),
            ("SMTP_FROM/SMTP_USER", sender),
        ]
        if not val
    ]
    if missing:
        raise RuntimeError(f"SMTP not configured. Missing: {', '.join(missing)}")

    safe_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in patient_name).strip("_")
    if not safe_name:
        safe_name = "patient"

    msg = EmailMessage()
    msg["Subject"] = f"Cat_Scriber: {patient_name} — {visit_date}"
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(
        f"Patient: {patient_name}\n"
        f"Visit date: {visit_date}\n"
        f"Detected language(s): {detected_language}\n\n"
        f"Attached:\n"
        f"  - transcription.txt — raw transcript from the visit recording\n"
        f"  - {safe_name}_chart.txt — generated SOAP-format chart note\n\n"
        f"Generated locally by Cat_Scriber. Review the chart before pasting into the EMR.\n"
    )

    msg.add_attachment(
        transcript_text.encode("utf-8"),
        maintype="text",
        subtype="plain",
        filename="transcription.txt",
    )
    msg.add_attachment(
        chart_text.encode("utf-8"),
        maintype="text",
        subtype="plain",
        filename=f"{safe_name}_chart.txt",
    )

    # certifi's CA bundle — the system bundle on macOS Python is often
    # incomplete and triggers CERTIFICATE_VERIFY_FAILED against Gmail's SMTP.
    context = ssl.create_default_context(cafile=certifi.where())
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(user, password)
            smtp.send_message(msg)
