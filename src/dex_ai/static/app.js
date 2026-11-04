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

// ---- Activity: one line per step, naming the model that did it ----
const MAX_ACTIVITY = 8;

function act(text, timed) {
  const li = el("li", { className: "act running" },
    el("span", { className: "act-icon", "aria-hidden": "true" }),
    el("span", { className: "act-text", textContent: text }));
  const list = $("activity");
  list.append(li);
  while (list.children.length > MAX_ACTIVITY) list.firstElementChild.remove();
  const started = performance.now();
  return {
    done(t, kind = "ok") {
      li.className = `act ${kind}`;
      const secs = ((performance.now() - started) / 1000).toFixed(1);
      li.querySelector(".act-text").textContent = kind === "ok" && timed ? `${t} · ${secs}s` : t;
    },
    fail(t) { this.done(t, "bad"); },
  };
}

// Receipts print merchants in capitals: "LUIGI'S TRATTORIA" -> "Luigi's Trattoria".
function titleCase(text) {
  if (!text || text !== text.toUpperCase()) return text;
  return text.toLowerCase().replace(/(^|[\s-])(\S)/g, (m, sep, ch) => sep + ch.toUpperCase());
}

// ---- Receipt: picking a photo starts everything ----
$("photo").addEventListener("change", (e) => {
  photo = e.target.files[0] || null;
  e.target.value = "";   // picking the same file again still fires
  if (photo) readReceipt();
});
$("new-receipt").addEventListener("click", () => $("photo").click());

async function readReceipt() {
  $("activity").replaceChildren();
  $("thumb").src = URL.createObjectURL(photo);
  $("sum-title").textContent = "Reading your receipt…";
  $("sum-meta").textContent = "";
  $("drop").hidden = true;
  $("receipt-summary").hidden = false;
  const a = act("Reading every line", true);
  try {
    const r = await postFile("/api/receipts/parse", "image", photo, photo.name);
    const bad = r.checks.filter((c) => !c.ok);
    a.done(`Read ${r.items.length} item${r.items.length === 1 ? "" : "s"}` +
      (bad.length ? "" : " · every sum checks out"), bad.length ? "warn" : "ok");
    for (const c of bad) act(c.message).done(c.message, "warn");
    $("sum-title").textContent = titleCase(r.merchant) || "Receipt";
    $("sum-meta").textContent = [r.date, money(r.total_cents)].filter(Boolean).join(" · ");
    greeting = `Got it: ${r.items.length} item${r.items.length === 1 ? "" : "s"}` +
      `${r.merchant ? ` from ${titleCase(r.merchant)}` : ""}, ${money(r.total_cents)} in all. ` +
      "Who had what? Tell me like you'd tell a friend.";
    loadReceipt(r);
  } catch (err) {
    a.fail(err.message);
    $("drop").hidden = false;
    $("receipt-summary").hidden = true;
  }
}

function loadReceipt(r) {
  receipt = r;
  assigned = new Map(r.items.map((it) => [it.id, new Set()]));
  weights = new Map();
  payer = ME;
  turns = [];
  approved = false;
  if (!greeting) greeting = "";
  spots = null;
  view = "list";
  saved = null;
  saveKey = null;
  renderConvo();
  $("voice-card").hidden = false;
  $("proposal-card").hidden = false;
  $("layout").classList.add("has-split");
  recompute();
  locateItems(photo, r);
}

// ---- Photo: SAM 3.1 places each item on the receipt, in the background ----
async function locateItems(file, r) {
  const a = act("Finding each item on your photo", true);
  try {
    const out = await postFile("/api/receipts/locate", "image", file, file.name, { receipt: JSON.stringify(r) });
    if (receipt !== r) return;          // a newer receipt was read meanwhile
    const placed = Object.keys(out.items).length;
    if (!placed) {                      // nothing placed confidently: stay on the list
      a.done("Couldn't pin items to the photo with confidence, so showing the list", "muted");
      return;
    }
    spots = out;
    $("photo-img").src = URL.createObjectURL(file);
    const missing = r.items.length - placed;
    a.done(`Marked ${placed} of ${r.items.length} items on your photo` + (missing ? ` (${missing} in the list only)` : ""));
    view = "photo";
    renderProposal();
  } catch {
    // The photo view is extra; the list works without it.
    a.done("Photo marking unavailable, so showing the list", "muted");
  }
}

document.querySelectorAll("#views button").forEach((b) => b.addEventListener("click", () => {
  view = b.dataset.view;
  renderProposal();
}));

function renderSpots(shares, everyone) {
  const pct = (v, of) => `${(100 * v) / of}%`;
  // Bands are level at the price and drop leftward by `slope`, following a tilted photo.
  $("spots").style.setProperty("--skew", `${Math.atan(-(spots.slope || 0))}rad`);
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
    // Everyone at the table gets one tag; four names would cover the item.
    const all = who.length > 2 && who.length === everyone.length;
    const tags = el("span", { className: "spot-tags" },
      ...(!who.length ? [el("span", { className: "tag todo", textContent: "?" })]
        : all ? [el("span", { className: "tag all-tag", textContent: "Everyone" })]
        : who.map((s) => el("span", { className: `tag ${colorOf(s.name)}`, textContent: label(s.name) }))));
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
  $("paper-head").textContent = [titleCase(receipt.merchant), receipt.date].filter(Boolean).join(" · ") || "Receipt";
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
    else if (p.total_cents > 0) who.append(el("small", { textContent: `owes ${result.payer === ME ? "you" : label(result.payer)}` }));
    return el("li", {}, el("details", {}, el("summary", {}, who, el("span", { className: "amt", textContent: money(p.total_cents) })), lines));
  }));

  $("payer").replaceChildren(...everyone.map((n) => new Option(label(n), n, false, n === payer)));
  $("payer").disabled = approved;
  $("options-summary").textContent = `Paid by ${label(payer)} · tax & tip ` +
    (taxTip === "equal" ? "split evenly" : "by what each person had");
  document.querySelectorAll("#taxtip button").forEach((b) => {
    b.setAttribute("aria-checked", String(b.dataset.mode === taxTip));
    b.disabled = approved;
  });

  // Who owes whom is on each person's row; the separate list only repeated it.
  $("settle-out").replaceChildren();

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
  // One key per approval: a retry or double tap of Save reuses it, so
  // Balance Desk saves this split once. Editing and approving again is a new
  // approval and gets a new key.
  if (!saved) saveKey = crypto.randomUUID();
  renderProposal();
  renderConvo();   // no undo once approved
  renderSave();
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
let greeting = "";   // Dex's first message once a receipt is read

function renderConvo() {
  const log = [];
  if (greeting) log.push(el("div", { className: "bubble dex" }, el("p", { textContent: greeting })));
  turns.forEach((t, i) => {
    log.push(el("div", { className: "bubble you" + (t.spoken ? " spoken" : "") }, el("p", { textContent: t.text })));
    if (t.pending) {
      log.push(el("div", { className: "bubble dex thinking" }, el("p", { textContent: "…" })));
      return;
    }
    if (t.error) {
      log.push(el("div", { className: "bubble dex error" }, el("p", { textContent: t.error })));
      return;
    }
    const dex = el("div", { className: "bubble dex" }, el("p", { textContent: t.out.summary || "Done." }));
    if (t.out.questions.length) {
      dex.append(el("ul", { className: "questions" }, ...t.out.questions.map((q) => el("li", { textContent: q }))));
    }
    if (t.out.actions.length) {
      dex.append(el("details", { className: "did" },
        el("summary", { textContent: `What I changed (${t.out.actions.length})` }),
        el("ul", {}, ...t.out.actions.map((a) => el("li", { textContent: describeAction(a) })))));
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
    log.push(dex);
  });
  $("convo").replaceChildren(...log);
  $("convo").scrollTop = $("convo").scrollHeight;
  $("talk-hint").textContent = turns.length
    ? "Fix anything the same way: “No, Aayush didn't have the fries” or “Kunal paid.”"
    : "Hold to talk, or type: “I had the pasta, Aayush and Ketan split the pizza, we all shared the fries.”";
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

async function runAgent(text, spoken = false) {
  if (!receipt) return act("").fail("Snap a receipt first");
  if (approved) { approved = false; }
  const turn = { text, spoken, pending: true, before: snapshot() };
  turns.push(turn);
  renderConvo();
  const a = act("Working out who had what", true);
  try {
    const out = await postJson("/api/assign", {
      receipt, transcript: text, assignments: currentAssignments(),
      people: people().filter((n) => n !== ME), payer, tax_tip: taxTip,
      contacts: bd.contacts || [], spoken,
    });
    turn.out = out;
    applyAgent(out);
    const items = new Set(out.actions.filter((x) => x.item_id).map((x) => x.item_id)).size;
    const added = out.added_people.length ? ` · added ${out.added_people.join(", ")}` : "";
    a.done(items ? `Updated ${items} item${items === 1 ? "" : "s"}${added}` : "Nothing to change", items ? "ok" : "muted");
    for (const q of out.questions) act("").done(`Dex asks: ${q}`, "warn");
  } catch (err) {
    turn.error = err.message;
    a.fail(err.message);
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
  } catch (err) {
    act("").fail("Microphone unavailable: " + err.message);
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
    act("").done("Hold the button while you talk", "muted");
    return;
  }
  const a = act("Listening", true);
  try {
    // People in the split and the receipt's items bias recognition toward the
    // words the split depends on. Contacts go to the agent instead: hinting all
    // of them made the recognizer hear "Arya and I each" as "Arya and Aayush"
    // (evals/REPORT.md).
    const items = receipt ? receipt.items.map((it) => it.name) : [];
    const r = await postFile("/api/voice/transcribe", "audio", encodeWav(chunks, SAMPLE_RATE), "speech.wav",
      { keywords: [...new Set([...people().filter((n) => n !== ME), ...items])].join(",") });
    if (!r.transcript) return a.done("Didn't catch that, try again", "muted");
    a.done("Got it");
    await runAgent(r.transcript, true);
  } catch (err) {
    a.fail(err.message);
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

// ---- Balance Desk: contacts to pick from, and saving an approved split ----
let bd = { linked: false };   // /api/balancedesk/context
let saveKey = null;           // idempotency key for this approval
let saved = null;             // Balance Desk's answer once this receipt is saved

async function loadBalanceDesk() {
  try {
    bd = await (await fetch("/api/balancedesk/context")).json();
  } catch {
    bd = { linked: false };
  }
  renderContacts();
}

function renderContacts() {
  const box = $("contacts");
  const named = new Set(people().map((n) => n.toLowerCase()));
  const options = (bd.contacts || []).filter((c) => !named.has(c.toLowerCase())).slice(0, 12);
  box.hidden = !bd.linked || !options.length;
  box.replaceChildren(el("span", { className: "meta", textContent: "Your contacts:" }), ...options.map((c) => {
    const b = el("button", { type: "button", className: "chip", textContent: `+ ${c}` });
    b.addEventListener("click", () => {
      $("people").value = [...people().filter((n) => n !== ME), c].join(", ");
      renderContacts();
      if (receipt) recompute();
    });
    return b;
  }));
}
$("people").addEventListener("input", renderContacts);

function newContacts() {
  const known = new Set((bd.contacts || []).map((c) => c.toLowerCase()));
  return result ? result.people.map((p) => p.name).filter((n) => n !== ME && !known.has(n.toLowerCase())) : [];
}

function renderSave() {
  const box = $("bd-save");
  box.hidden = !approved || !bd.linked;
  if (box.hidden) return;
  const iPaid = result && result.payer === ME;
  $("bd-method-field").hidden = !iPaid || !!saved;
  if (iPaid && !$("bd-methods").options.length) {
    const methods = bd.payment_methods || [];
    $("bd-methods").replaceChildren(...methods.map((m) => new Option(m, m)));
    if (!$("bd-method").value && methods.length) $("bd-method").value = methods[0];
  }
  const fresh = newContacts();
  $("bd-new").textContent = saved ? "" : fresh.length ? `Saving adds ${fresh.join(", ")} as new contact${fresh.length > 1 ? "s" : ""}.` : "";
  const btn = $("bd-save-btn");
  if (saved) {
    btn.disabled = true;
    btn.textContent = "Saved to Balance Desk ✓";
    setStatus($("bd-status"), `Expense #${saved.expense.id}${saved.replayed ? " (already saved earlier)" : ""}. ` +
      "Edits from here on won't change it; edit it in Balance Desk.");
  } else {
    btn.disabled = false;
    btn.textContent = "Save to Balance Desk";
  }
}

$("bd-save-btn").addEventListener("click", async () => {
  if (saved || !saveKey) return;
  const btn = $("bd-save-btn");
  btn.disabled = true;
  btn.textContent = "Saving…";
  setStatus($("bd-status"), "");
  try {
    saved = await postJson("/api/balancedesk/save", {
      receipt, assignments: currentAssignments(), payer, tax_tip: taxTip,
      payment_method: $("bd-method").value.trim() || null,
      idempotency_key: saveKey,
      allow_new_contacts: newContacts().length > 0,
    });
    // Contacts Balance Desk just created are known from now on.
    bd.contacts = [...new Set([...(bd.contacts || []), ...newContacts()])];
  } catch (err) {
    setStatus($("bd-status"), err.message + " (safe to try again: it can only save once)", true);
  }
  renderSave();
});

loadBalanceDesk();
