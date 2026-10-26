// Capture page: receipt photo -> /api/receipts/parse, held mic -> WAV -> /api/voice/transcribe.
const $ = (id) => document.getElementById(id);
const money = (cents) => (cents == null ? "—" : (cents < 0 ? "−$" : "$") + (Math.abs(cents) / 100).toFixed(2));

function setStatus(el, text, isError = false) {
  el.textContent = text;
  el.classList.toggle("error", isError);
}

async function postFile(url, field, blob, filename, extra = {}) {
  const form = new FormData();
  form.append(field, blob, filename);
  for (const [k, v] of Object.entries(extra)) form.append(k, v);
  const resp = await fetch(url, { method: "POST", body: form });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(body.detail || `Request failed (${resp.status})`);
  return body;
}

// ---- Receipt ----
let photo = null;
let receipt = null;

$("photo").addEventListener("change", (e) => {
  photo = e.target.files[0] || null;
  if (!photo) return;
  $("preview").src = URL.createObjectURL(photo);
  $("preview").hidden = false;
  $("drop-hint").hidden = true;
  $("read-btn").disabled = false;
  $("receipt-out").hidden = true;
  setStatus($("receipt-status"), "");
});

$("read-btn").addEventListener("click", async () => {
  if (!photo) return;
  $("read-btn").disabled = true;
  setStatus($("receipt-status"), "Reading with Muse Spark…");
  const started = performance.now();
  try {
    const r = await postFile("/api/receipts/parse", "image", photo, photo.name);
    renderReceipt(r);
    setStatus($("receipt-status"), `Read ${r.items.length} items in ${((performance.now() - started) / 1000).toFixed(1)}s`);
  } catch (err) {
    setStatus($("receipt-status"), err.message, true);
  } finally {
    $("read-btn").disabled = false;
  }
});

function renderReceipt(r) {
  receipt = r;
  $("receipt-meta").textContent = [r.merchant, r.date].filter(Boolean).join(" · ");
  $("items").replaceChildren(...r.items.map((it) => row([it.name, it.quantity, money(it.amount_cents)])));
  const foot = [
    ["Subtotal", r.subtotal_cents],
    ...r.other_charges.map((c) => [c.name, c.amount_cents]),
    ["Tax", r.tax_cents],
    ["Tip", r.tip_cents],
  ].filter(([, v]) => v != null).map(([k, v]) => row([k, "", money(v)]));
  const total = row(["Total", "", money(r.total_cents)]);
  total.className = "total";
  $("totals").replaceChildren(...foot, total);
  $("checks").replaceChildren(...r.checks.map((c) => {
    const li = document.createElement("li");
    li.className = c.ok ? "ok" : "bad";
    li.textContent = (c.ok ? "✓ " : "⚠ ") + c.message;
    return li;
  }));
  $("receipt-out").hidden = false;
}

function row(cells) {
  const tr = document.createElement("tr");
  cells.forEach((text, i) => {
    const td = document.createElement("td");
    td.textContent = text;
    if (i > 0) td.className = "num";
    tr.appendChild(td);
  });
  return tr;
}

// ---- Voice: record mono PCM at 16 kHz and encode WAV in the browser ----
const SAMPLE_RATE = 16000;
let rec = null;

async function startRecording() {
  if (rec) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
    const source = ctx.createMediaStreamSource(stream);
    const node = ctx.createScriptProcessor(4096, 1, 1);
    const chunks = [];
    node.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
    source.connect(node);
    node.connect(ctx.destination);
    rec = { stream, ctx, node, chunks, started: performance.now() };
    $("mic-btn").setAttribute("aria-pressed", "true");
    $("mic-label").textContent = "Listening… release to send";
    setStatus($("voice-status"), "");
  } catch (err) {
    setStatus($("voice-status"), "Microphone unavailable: " + err.message, true);
  }
}

async function stopRecording() {
  if (!rec) return;
  const { stream, ctx, node, chunks, started } = rec;
  rec = null;
  node.disconnect();
  stream.getTracks().forEach((t) => t.stop());
  await ctx.close();
  $("mic-btn").setAttribute("aria-pressed", "false");
  $("mic-label").textContent = "Hold to talk";
  if (performance.now() - started < 400) {
    setStatus($("voice-status"), "Hold the button while you talk", true);
    return;
  }
  setStatus($("voice-status"), "Transcribing with Muse Voice Transcribe…");
  try {
    // Names and item names bias recognition toward words the split depends on.
    const people = $("people").value.split(",").map((s) => s.trim()).filter(Boolean);
    const items = receipt ? receipt.items.map((it) => it.name) : [];
    const r = await postFile("/api/voice/transcribe", "audio", encodeWav(chunks, SAMPLE_RATE), "speech.wav",
      { keywords: [...people, ...items].join(",") });
    $("transcript").textContent = r.transcript || "(nothing heard)";
    $("transcript").hidden = false;
    setStatus($("voice-status"), r.duration_ms ? `${(r.duration_ms / 1000).toFixed(1)}s of audio` : "");
  } catch (err) {
    setStatus($("voice-status"), err.message, true);
  }
}

function encodeWav(chunks, rate) {
  const length = chunks.reduce((n, c) => n + c.length, 0);
  const view = new DataView(new ArrayBuffer(44 + length * 2));
  const str = (off, s) => [...s].forEach((ch, i) => view.setUint8(off + i, ch.charCodeAt(0)));
  str(0, "RIFF"); view.setUint32(4, 36 + length * 2, true); str(8, "WAVE");
  str(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  str(36, "data"); view.setUint32(40, length * 2, true);
  let off = 44;
  for (const c of chunks) for (const s of c) {
    const v = Math.max(-1, Math.min(1, s));
    view.setInt16(off, v < 0 ? v * 0x8000 : v * 0x7fff, true);
    off += 2;
  }
  return new Blob([view], { type: "audio/wav" });
}

const mic = $("mic-btn");
mic.addEventListener("pointerdown", (e) => { e.preventDefault(); startRecording(); });
["pointerup", "pointerleave", "pointercancel"].forEach((ev) => mic.addEventListener(ev, stopRecording));
mic.addEventListener("keydown", (e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) { e.preventDefault(); startRecording(); } });
mic.addEventListener("keyup", (e) => { if (e.key === " " || e.key === "Enter") stopRecording(); });
