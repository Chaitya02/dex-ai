// Dex · Split it. Receipt photo -> items; voice or text -> agent -> assignments;
// assignments -> /api/split -> a live proposal drawn as the receipt itself.
const $ = (id) => document.getElementById(id);
const money = (cents) => (cents == null ? "—" : (cents < 0 ? "−$" : "$") + (Math.abs(cents) / 100).toFixed(2));
const ME = "me";
const label = (name) => (name === ME ? "Me" : name);

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children.filter((c) => c != null));
  return node;
}

function setStatus(node, text, isError = false) {
  node.textContent = text;
  node.classList.toggle("error", isError);
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

async function postJson(url, payload) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${resp.status})`);
  return body;
}

// ---- State ----
let photo = null;
let receipt = null;
let assigned = new Map();   // item id -> Set of names
let weights = new Map();    // item id -> {name: portion}, only for unequal shares
let payer = ME;
let taxTip = "proportional";
let result = null;          // latest /api/split response
let editing = null;         // item id whose chips are open
let changed = new Set();    // item ids the last Dex turn touched
let turns = [];             // [{text, out, before}] conversation with Dex
let approved = false;
let spots = null;           // /api/receipts/locate result: item boxes on the photo
let view = "list";          // "photo" once SAM has placed items

// Stable colour per person, in the order they were first named.
const PALETTE = 7;
function colorOf(name) {
  if (name === ME) return "c-me";
  const i = people().filter((n) => n !== ME).indexOf(name);
  return `c-${(i < 0 ? 0 : i) % PALETTE}`;
}

function people() {
  const named = $("people").value.split(",").map((s) => s.trim()).filter(Boolean);
  const seen = new Set([ME]);
  const out = [ME];
  for (const n of named) if (!seen.has(n.toLowerCase())) { seen.add(n.toLowerCase()); out.push(n); }
  return out;
}

function snapshot() {
  return {
    assigned: new Map([...assigned].map(([k, v]) => [k, new Set(v)])),
    weights: new Map(weights),
    people: $("people").value,
    payer,
    taxTip,
  };
}

function restore(s) {
  assigned = s.assigned;
  weights = s.weights;
  $("people").value = s.people;
  payer = s.payer;
  taxTip = s.taxTip;
}

function currentAssignments() {
  return [...assigned].filter(([, s]) => s.size).map(([id, s]) =>
    weights.has(id) ? { item_id: id, weights: weights.get(id) } : { item_id: id, people: [...s] });
}

// ---- Receipt ----
$("photo").addEventListener("change", (e) => {
  photo = e.target.files[0] || null;
  if (!photo) return;
  $("preview").src = URL.createObjectURL(photo);
  $("preview").hidden = false;
  $("drop-hint").hidden = true;
  $("read-btn").disabled = false;
  setStatus($("receipt-status"), "");
});

$("read-btn").addEventListener("click", async () => {
  if (!photo) return;
  $("read-btn").disabled = true;
  setStatus($("receipt-status"), "Reading with Muse Spark…");
  const started = performance.now();
  try {
    const r = await postFile("/api/receipts/parse", "image", photo, photo.name);
    loadReceipt(r);
    const where = [r.merchant, r.date].filter(Boolean).join(" · ");
    setStatus($("receipt-status"), `Read ${r.items.length} items${where ? ` from ${where}` : ""} in ${((performance.now() - started) / 1000).toFixed(1)}s`);
  } catch (err) {
    setStatus($("receipt-status"), err.message, true);
  } finally {
    $("read-btn").disabled = false;
  }
});

function loadReceipt(r) {
  receipt = r;
  assigned = new Map(r.items.map((it) => [it.id, new Set()]));
  weights = new Map();
  payer = ME;
  turns = [];
  approved = false;
  $("checks").replaceChildren(...r.checks.map((c) =>
    el("li", { className: c.ok ? "ok" : "bad", textContent: (c.ok ? "✓ " : "⚠ ") + c.message })));
  spots = null;
  view = "list";
  renderConvo();
  $("proposal-card").hidden = false;
  recompute();
  locateItems(photo, r);
}

// ---- Photo: SAM 3.1 places each item on the receipt, in the background ----
async function locateItems(file, r) {
  setStatus($("sam-note"), "");
  try {
    const out = await postFile("/api/receipts/locate", "image", file, file.name, { receipt: JSON.stringify(r) });
    if (receipt !== r) return;          // a newer receipt was read meanwhile
    const placed = Object.keys(out.items).length;
    if (!placed) return;                // nothing placed confidently: stay on the list
    spots = out;
    $("photo-img").src = URL.createObjectURL(file);
    const missing = r.items.length - placed;
    setStatus($("sam-note"), `SAM 3.1 placed ${placed} of ${r.items.length} items on your photo` +
      (missing ? ` · ${missing} shown only in the list` : ""));
    view = "photo";
    renderProposal();
  } catch {
    // The photo view is extra; the list works without it.
  }
}

document.querySelectorAll("#views button").forEach((b) => b.addEventListener("click", () => {
  view = b.dataset.view;
  renderProposal();
}));

function renderSpots(shares, everyone) {
  const pct = (v, of) => `${(100 * v) / of}%`;
  $("spots").replaceChildren(...receipt.items.filter((it) => spots.items[it.id]).map((it) => {
    const b = spots.items[it.id];
    const who = shares.get(it.id) || [];
    const first = who.length ? colorOf(who[0].name) : "todo";
    const spot = el("button", {
      type: "button",
      className: `spot ${first}` + (editing === it.id ? " open" : "") + (changed.has(it.id) ? " changed" : ""),
      disabled: approved,
      style: `left:${pct(b.x1, spots.width)};top:${pct(b.y1, spots.height)};` +
             `width:${pct(b.x2 - b.x1, spots.width)};height:${pct(b.y2 - b.y1, spots.height)}`,
    });
    spot.setAttribute("aria-label", `${it.name}: ${who.length ? who.map((s) => label(s.name)).join(", ") : "unassigned"}`);
    spot.addEventListener("click", () => { editing = editing === it.id ? null : it.id; renderProposal(); });
    const tags = el("span", { className: "spot-tags" },
      ...(who.length ? who.map((s) => el("span", { className: `tag ${colorOf(s.name)}`, textContent: label(s.name) }))
                     : [el("span", { className: "tag todo", textContent: "?" })]));
    spot.append(tags);
    return spot;
  }));
  const open = receipt.items.find((it) => it.id === editing && spots.items[it.id]);
  $("photo-editor").replaceChildren(...(open && !approved
    ? [el("p", { className: "meta", textContent: `Who had ${open.name}?` }), chipEditor(open, everyone)]
    : []));
}

// ---- Proposal: recompute on every change, draw it as the receipt ----
let splitSeq = 0;
async function recompute() {
  if (!receipt) return;
  const everyone = people();
  for (const [id, set] of assigned) {
    for (const n of [...set]) if (!everyone.includes(n)) { set.delete(n); weights.delete(id); }
  }
  if (!everyone.includes(payer)) payer = ME;
  const seq = ++splitSeq;
  try {
    const s = await postJson("/api/split", { receipt, assignments: currentAssignments(), payer, tax_tip: taxTip });
    if (seq !== splitSeq) return;   // a newer change already won
    result = s;
    renderProposal();
  } catch (err) {
    setStatus($("balance-out"), err.message, true);
  }
}

function sharesByItem() {
  const map = new Map();
  for (const p of result.people) for (const it of p.items) {
    if (!map.has(it.item_id)) map.set(it.item_id, []);
    map.get(it.item_id).push({ name: p.name, cents: it.cents });
  }
  return map;
}

function renderProposal() {
  const shares = sharesByItem();
  const everyone = people();
  $("paper-head").textContent = [receipt.merchant, receipt.date].filter(Boolean).join(" · ") || "Receipt";
  const onPhoto = !!spots && view === "photo";
  $("views").hidden = !spots;
  document.querySelectorAll("#views button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.view === view)));
  $("photo-view").hidden = !onPhoto;
  $("paper").hidden = onPhoto;
  if (onPhoto) renderSpots(shares, everyone);

  $("lines-out").replaceChildren(...receipt.items.map((it) => {
    const who = shares.get(it.id) || [];
    const open = !approved && (editing === it.id || who.length === 0);
    const li = el("li", { className: "line" + (who.length ? "" : " todo") + (changed.has(it.id) ? " changed" : "") });
    const head = el("button", { type: "button", className: "line-head", disabled: approved },
      el("span", { className: "line-name", textContent: it.quantity > 1 ? `${it.quantity} × ${it.name}` : it.name }),
      el("span", { className: "line-amt", textContent: money(it.amount_cents) }));
    head.setAttribute("aria-expanded", String(open));
    head.addEventListener("click", () => { editing = editing === it.id ? null : it.id; renderProposal(); });
    const tags = el("div", { className: "tags" });
    if (who.length) {
      const w = weights.get(it.id);
      for (const s of who) {
        const portion = w ? ` ×${w[s.name]}` : "";
        tags.append(el("span", { className: `tag ${colorOf(s.name)}`, textContent: `${label(s.name)}${portion} ${money(s.cents)}` }));
      }
    } else {
      tags.append(el("span", { className: "ask", textContent: "Who had this?" }));
    }
    li.append(head, tags);
    if (open) li.append(chipEditor(it, everyone));
    return li;
  }));

  const rows = [
    ["Subtotal", receipt.subtotal_cents],
    ...receipt.other_charges.map((c) => [c.name, c.amount_cents]),
    ["Tax", receipt.tax_cents],
    ["Tip", receipt.tip_cents],
  ].filter(([, v]) => v != null);
  $("paper-totals").replaceChildren(
    ...rows.flatMap(([k, v]) => [el("dt", { textContent: k }), el("dd", { textContent: money(v) })]),
    el("dt", { className: "grand", textContent: "Total" }),
    el("dd", { className: "grand", textContent: money(receipt.total_cents) }));

  // Who's paying what share of the bill, as one stacked bar.
  const total = result.people.reduce((n, p) => n + Math.max(p.total_cents, 0), 0) || 1;
  $("bar").replaceChildren(...result.people.filter((p) => p.total_cents > 0).map((p) =>
    el("span", { className: colorOf(p.name), style: `flex-basis:${(100 * p.total_cents) / total}%`, title: `${label(p.name)} ${money(p.total_cents)}` })));

  $("people-out").replaceChildren(...result.people.map((p) => {
    const lines = el("ul", { className: "lines" },
      ...p.items.map((it) => line(it.name + (it.split_ways > 1 ? ` (1/${it.split_ways} of ${money(it.of_cents)})` : ""), money(it.cents))),
      ...p.extras.map((e) => line(e.name, money(e.cents))));
    const who = el("span", { className: "who" }, el("i", { className: `swatch ${colorOf(p.name)}` }), label(p.name));
    if (p.name === result.payer) who.append(el("small", { textContent: "paid" }));
    return el("li", {}, el("details", {}, el("summary", {}, who, el("span", { className: "amt", textContent: money(p.total_cents) })), lines));
  }));

  $("payer").replaceChildren(...everyone.map((n) => new Option(label(n), n, false, n === payer)));
  $("payer").disabled = approved;
  document.querySelectorAll("#taxtip button").forEach((b) => {
    b.setAttribute("aria-checked", String(b.dataset.mode === taxTip));
    b.disabled = approved;
  });

  $("settle-out").replaceChildren(...result.settlements.map((t) =>
    el("div", {}, el("span", { textContent: `${label(t.from)} → ${label(t.to)}` }), el("strong", { textContent: money(t.cents) }))));

  const parts = [`Split ${money(result.split_total_cents)}`];
  if (result.receipt_total_cents != null) parts.push(`of ${money(result.receipt_total_cents)}`);
  if (result.unassigned.length) parts.push(`· ${result.unassigned.length} item(s) still need someone`);
  else if (result.balanced) parts.push("· every cent accounted for ✓");
  else parts.push("· doesn't match the receipt total, check the receipt above");
  setStatus($("balance-out"), parts.join(" "), !result.unassigned.length && !result.balanced);

  const badge = $("state-badge");
  badge.textContent = approved ? "Approved" : result.unassigned.length ? "Needs you" : "Proposed";
  badge.className = "badge " + (approved ? "ok" : result.unassigned.length ? "warn" : "");
  $("approve-btn").disabled = approved || !result.balanced;
  $("approve-btn").hidden = approved;
  $("approved").hidden = !approved;
  if (approved) $("settle-msg").textContent = settleMessage();
}

function chipEditor(it, everyone) {
  const set = assigned.get(it.id);
  const chips = el("div", { className: "chips" });
  // A tap means "equal split again", so it drops any unequal weights.
  const edit = (fn) => () => { weights.delete(it.id); fn(); changed = new Set(); recompute(); };
  for (const n of everyone) {
    chips.append(chip(label(n), set.has(n), colorOf(n), edit(() => (set.has(n) ? set.delete(n) : set.add(n)))));
  }
  const all = everyone.every((n) => set.has(n));
  chips.append(chip("Everyone", all, "all", edit(() => everyone.forEach((n) => (all ? set.delete(n) : set.add(n))))));
  return chips;
}

function chip(text, on, cls, onClick) {
  const b = el("button", { type: "button", className: `chip ${cls}`, textContent: text });
  b.setAttribute("aria-pressed", String(on));
  b.addEventListener("click", onClick);
  return b;
}

function line(left, right) {
  return el("li", {}, el("span", { textContent: left }), el("span", { textContent: right }));
}

$("people").addEventListener("input", () => { if (receipt) recompute(); });
$("payer").addEventListener("change", (e) => { payer = e.target.value; recompute(); });
document.querySelectorAll("#taxtip button").forEach((b) => b.addEventListener("click", () => {
  taxTip = b.dataset.mode;
  recompute();
}));

// ---- Approve ----
function settleMessage() {
  const head = [receipt.merchant, receipt.date].filter(Boolean).join(", ");
  const you = (n) => (n === ME ? "me" : n);
  const lines = result.settlements.map((t) => `${you(t.from)} owes ${you(t.to)} ${money(t.cents)}`);
  return [`${head || "Our bill"}: ${money(result.split_total_cents)} total`, ...lines].join("\n");
}

$("approve-btn").addEventListener("click", () => {
  approved = true;
  editing = null;
  renderProposal();
  renderConvo();   // no undo once approved
});
$("edit-btn").addEventListener("click", () => {
  approved = false;
  renderProposal();
  renderConvo();
});
$("copy-btn").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(settleMessage());
    $("copy-btn").textContent = "Copied";
    setTimeout(() => ($("copy-btn").textContent = "Copy message"), 1500);
  } catch {
    $("copy-btn").textContent = "Copy blocked: select the text";
  }
});

// ---- Conversation with Dex ----
function renderConvo() {
  $("convo").replaceChildren(...turns.map((t, i) => {
    const li = el("li", { className: "turn" });
    li.append(el("p", { className: "you", textContent: t.text }));
    if (t.pending) {
      li.append(el("p", { className: "dex thinking", textContent: "Dex is working on it…" }));
      return li;
    }
    if (t.error) {
      li.append(el("p", { className: "dex error", textContent: t.error }));
      return li;
    }
    const dex = el("div", { className: "dex" }, el("p", { textContent: t.out.summary || "Done." }));
    if (t.out.actions.length) {
      dex.append(el("details", { className: "did" },
        el("summary", { textContent: `What Dex did (${t.out.actions.length})` }),
        el("ul", {}, ...t.out.actions.map((a) => el("li", { textContent: describeAction(a) })))));
    }
    if (t.out.questions.length) {
      dex.append(el("ul", { className: "questions" }, ...t.out.questions.map((q) => el("li", { textContent: q }))));
    }
    if (i === turns.length - 1 && t.before && !approved) {
      const undo = el("button", { type: "button", className: "link", textContent: "Undo" });
      undo.addEventListener("click", () => {
        restore(t.before);
        turns.pop();
        changed = new Set();
        renderConvo();
        recompute();
      });
      dex.append(undo);
    }
    li.append(dex);
    return li;
  }));
  $("talk-hint").textContent = turns.length
    ? "Say a fix: “No, Aayush didn't have the fries” or “Kunal paid.”"
    : "Hold the button and talk: “I had the pasta, Aayush and Ketan split the pizza, everyone shared the fries.”";
}

function describeAction(a) {
  switch (a.tool) {
    case "assign_item": {
      const w = a.weights || {};
      const unequal = new Set(Object.values(w)).size > 1;
      return `${a.item} → ${a.people.map((n) => label(n) + (unequal ? ` ×${w[n]}` : "")).join(", ")}`;
    }
    case "unassign_item": return `${a.item} → cleared`;
    case "add_person": return `Added ${a.name}`;
    case "set_payer": return `Paid by ${label(a.name)}`;
    case "set_tax_tip": return `Tax & tip: ${a.mode === "equal" ? "split evenly" : "by what you had"}`;
    default: return a.tool;
  }
}

$("type-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("typed").value.trim();
  if (!text) return;
  $("typed").value = "";
  await runAgent(text);
});

async function runAgent(text) {
  if (!receipt) return setStatus($("voice-status"), "Read a receipt first", true);
  if (approved) { approved = false; }
  const turn = { text, pending: true, before: snapshot() };
  turns.push(turn);
  renderConvo();
  setStatus($("voice-status"), "");
  try {
    const out = await postJson("/api/assign", {
      receipt, transcript: text, assignments: currentAssignments(),
      people: people().filter((n) => n !== ME), payer, tax_tip: taxTip,
    });
    turn.out = out;
    applyAgent(out);
  } catch (err) {
    turn.error = err.message;
  } finally {
    turn.pending = false;
    renderConvo();
  }
}

function applyAgent(out) {
  const named = people().filter((n) => n !== ME);
  for (const n of out.added_people) if (!named.includes(n)) named.push(n);
  $("people").value = named.join(", ");
  assigned = new Map(receipt.items.map((it) => [it.id, new Set()]));
  for (const a of out.assignments) assigned.set(a.item_id, new Set(Object.keys(a.weights)));
  weights = new Map(out.assignments
    .filter((a) => new Set(Object.values(a.weights)).size > 1)
    .map((a) => [a.item_id, a.weights]));
  payer = out.payer;
  taxTip = out.tax_tip;
  changed = new Set(out.actions.filter((a) => a.item_id).map((a) => a.item_id));
  editing = null;
  recompute();
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
    const items = receipt ? receipt.items.map((it) => it.name) : [];
    const r = await postFile("/api/voice/transcribe", "audio", encodeWav(chunks, SAMPLE_RATE), "speech.wav",
      { keywords: [...people().filter((n) => n !== ME), ...items].join(",") });
    setStatus($("voice-status"), "");
    if (!r.transcript) return setStatus($("voice-status"), "Didn't catch that, try again", true);
    await runAgent(r.transcript);
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
