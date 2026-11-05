const form = document.getElementById("upload-form");
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("audio-input");
const dropzoneLabel = document.getElementById("dropzone-label");
const submitBtn = document.getElementById("submit-btn");
const statusSection = document.getElementById("status");
const stageLine = document.getElementById("stage-line");
const progressBar = document.getElementById("progress-bar");
const messageEl = document.getElementById("message");
const errorEl = document.getElementById("error");
const resultsSection = document.getElementById("results");
const chartEl = document.getElementById("chart-text");
const transcriptEl = document.getElementById("transcript-text");

const STAGE_LABELS = {
  queued: "Queued",
  transcribing: "Transcribing audio",
  charting: "Generating chart with Claude",
  emailing: "Sending email",
  done: "Done",
  error: "Error",
};

["dragenter", "dragover"].forEach((evt) =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  })
);
["dragleave", "drop"].forEach((evt) =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
  })
);
dropzone.addEventListener("drop", (e) => {
  if (e.dataTransfer.files.length) {
    fileInput.files = e.dataTransfer.files;
    updateDropzone();
  }
});
fileInput.addEventListener("change", updateDropzone);

function updateDropzone() {
  const f = fileInput.files[0];
  if (f) {
    dropzone.classList.add("has-file");
    const sizeMB = (f.size / (1024 * 1024)).toFixed(1);
    dropzoneLabel.textContent = `${f.name} (${sizeMB} MB) — click to choose a different file`;
  } else {
    dropzone.classList.remove("has-file");
    dropzoneLabel.textContent = "Drag & drop audio here, or click to choose";
  }
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  errorEl.hidden = true;
  resultsSection.hidden = true;
  statusSection.hidden = false;
  submitBtn.disabled = true;
  stageLine.textContent = "Uploading...";
  progressBar.value = 0;
  messageEl.textContent = "";

  const formData = new FormData(form);
  let res;
  try {
    res = await fetch("/upload", { method: "POST", body: formData });
  } catch (err) {
    showError(`Upload failed: ${err.message}`);
    return;
  }
  if (!res.ok) {
    const t = await res.text();
    showError(`Upload rejected (${res.status}): ${t}`);
    return;
  }
  const { job_id } = await res.json();
  pollJob(job_id);
});

async function pollJob(jobId) {
  while (true) {
    let data;
    try {
      const r = await fetch(`/jobs/${jobId}`);
      if (!r.ok) {
        showError(`Status check failed: ${r.status}`);
        return;
      }
      data = await r.json();
    } catch (err) {
      showError(`Status check error: ${err.message}`);
      return;
    }

    stageLine.textContent = STAGE_LABELS[data.stage] || data.stage;
    messageEl.textContent = data.message || "";

    if (data.stage === "transcribing") {
      progressBar.value = data.progress;
    } else if (data.stage === "queued") {
      progressBar.value = 0;
    } else if (data.stage === "done") {
      progressBar.value = 1;
    }

    if (data.stage === "done") {
      submitBtn.disabled = false;
      chartEl.textContent = data.chart || "";
      transcriptEl.textContent = data.transcript || "";
      resultsSection.hidden = false;
      return;
    }
    if (data.stage === "error") {
      showError(data.error || "Pipeline failed");
      return;
    }

    await new Promise((r) => setTimeout(r, 1500));
  }
}

function showError(msg) {
  submitBtn.disabled = false;
  errorEl.textContent = msg;
  errorEl.hidden = false;
}
