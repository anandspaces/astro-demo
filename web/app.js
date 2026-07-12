const $ = (id) => document.getElementById(id);
const esc = (s) => s.replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

const api = async (path, opts) => {
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({ error: "bad JSON from server" }));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
};

let currentUser = localStorage.getItem("starsage_user") || "";
let sending = false;   // a reading is currently streaming
const session = "web-" + Math.random().toString(36).slice(2, 8);

function setUser(id) {
  currentUser = id;
  localStorage.setItem("starsage_user", id || "");
  $("activeUser").textContent = id ? `· ${id.slice(0, 8)}…` : "";
  updateChatGate();
}

/* Chat is only usable once a chart exists — gate the composer + chips and guide
   first-time users to compute a chart first. */
function updateChatGate() {
  const ready = !!currentUser;
  $("chat").dataset.state = ready ? "ready" : "nochart";
  $("chartBtn").hidden = !ready;
  $("msg").disabled = !ready;
  $("msg").placeholder = ready
    ? "Ask about career, marriage, wealth, the year ahead…"
    : "Compute your chart to begin…";
  document.querySelectorAll(".chip").forEach(c => c.disabled = !ready || sending);
  $("chartPanel").classList.toggle("needs-attention", !ready);
  updateSendState();
}
function updateSendState() {
  $("send").disabled = sending || !currentUser || !$("msg").value.trim();
}
function setSending(on) {
  sending = on;
  $("msg").disabled = on || !currentUser;
  document.querySelectorAll(".chip").forEach(c => c.disabled = on || !currentUser);
  updateSendState();
}

async function loadProvider() {
  try {
    const p = await api("/api/provider");
    const keys = Object.entries(p.keys).filter(([, v]) => v).map(([k]) => k).join(", ") || "none — add in ⚙";
    $("provider").innerHTML = `<span class="dot"></span> ${esc(p.provider)} · keys: ${esc(keys)}`;
    $("provider").classList.add("live");
  } catch { $("provider").innerHTML = `<span class="dot"></span> offline`; }
}

/* Chat-box model switcher: named after the actual saved default, and only offers
   providers you've actually configured. Hidden entirely unless you have 2+, since
   there's nothing to switch between with one. Empty value = use saved settings. */
async function refreshModelSelect() {
  let s;
  try { s = await api("/api/settings"); } catch { return; }
  const configured = KNOWN_PROVIDERS.filter(p => s.keys?.[p]?.set);
  const sel = $("provSel"), wrap = $("modelToggle");
  if (configured.length < 2) { sel.innerHTML = `<option value="">`; wrap.hidden = true; return; }
  const active = configured.includes(s.provider) ? s.provider : configured[0];
  const model = s.models?.[active]?.chosen || s.models?.[active]?.default || "";
  const opts = [`<option value="">${PROV_LABEL[active]}${model ? " · " + esc(model) : ""} (default)</option>`];
  configured.filter(p => p !== active).forEach(p => opts.push(`<option value="${p}">${PROV_LABEL[p]}</option>`));
  sel.innerHTML = opts.join("");
  wrap.hidden = false;
}

/* ===================== MODEL & API-KEY POPUP ===================== */
const KNOWN_PROVIDERS = ["claude", "gpt", "gemini"];   // the only providers the UI renders
const PROV_LABEL = { claude: "Claude", gpt: "GPT", gemini: "Gemini" };
const providerList = () => (settings?.providers || KNOWN_PROVIDERS).filter(p => KNOWN_PROVIDERS.includes(p));
let settings = null;
let pendingProvider = "";
const pendingKeys = {};    // provider -> raw string (set) or null (clear)
const pendingModels = {};  // provider -> model id (typed)
const modelLists = {};     // provider -> [model ids] fetched live/fallback

const anyKeySet = () =>
  Object.values(settings?.keys || {}).some(k => k.set) ||
  Object.values(pendingKeys).some(v => typeof v === "string");

function openSettings() {
  loadSettings().then(() => { $("settingsModal").hidden = false; })
    .catch(e => alert("Could not load settings: " + e.message));
}
function closeSettings() {
  if (!anyKeySet()) { $("settingsGate").hidden = false; return; }   // gate: need a key
  $("settingsModal").hidden = true;
}
$("openSettings").onclick = openSettings;
$("closeSettings").onclick = closeSettings;
$("settingsModal").onclick = (e) => { if (e.target === $("settingsModal")) closeSettings(); };
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("settingsModal").hidden) closeSettings(); });

async function loadSettings() {
  settings = await api("/api/settings");
  pendingProvider = KNOWN_PROVIDERS.includes(settings.provider) ? settings.provider : (providerList()[0] || "claude");
  for (const k in pendingKeys) delete pendingKeys[k];
  for (const k in pendingModels) delete pendingModels[k];
  renderSettings();
  // preload model lists for providers that already have a stored key
  providerList().forEach(p => { if (settings.keys?.[p]?.set) fetchModels(p); });
}

async function fetchModels(p, btn) {
  if (btn) { btn.disabled = true; btn.dataset.label = btn.textContent; btn.textContent = "loading…"; }
  try {
    const r = await api(`/api/models?provider=${p}`);
    modelLists[p] = r.models || [];
    renderSettings();
  } catch { /* keep whatever we have */ }
  finally { if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label || "refresh"; } }
}

function currentModel(p) {
  if (p in pendingModels) return pendingModels[p];
  return settings.models?.[p]?.chosen || "";
}

function renderSettings() {
  const provs = providerList();

  // active-provider segmented control
  $("providerCards").innerHTML =
    `<div class="segmented" role="tablist">` +
    provs.map(p => `<button type="button" role="tab" aria-selected="${pendingProvider === p}" class="seg${pendingProvider === p ? " active" : ""}" data-p="${p}">${PROV_LABEL[p] || p}</button>`).join("") +
    `</div>`;
  $("providerCards").querySelectorAll(".seg").forEach(el => el.onclick = () => {
    pendingProvider = el.dataset.p; renderSettings();
  });

  // only the selected provider's key + model
  const p = pendingProvider;
  const k = settings.keys?.[p] || {};
  const pending = pendingKeys[p];
  let cls = "muted", txt = "not set";
  if (pending === null) { cls = "warn"; txt = "will clear on save"; }
  else if (typeof pending === "string") { cls = "ok"; txt = "new key entered"; }
  else if (k.set) { cls = "ok"; txt = `stored · ${esc(k.hint)}`; }
  const opts = (modelLists[p] || []).map(m => `<option value="${esc(m)}">`).join("");
  const def = settings.models?.[p]?.default || "";
  $("keyRows").innerHTML = `<div class="provblock">
      <div class="pb-head"><span class="pb-name">${PROV_LABEL[p]}</span><span class="kstate ${cls}">${txt}</span></div>
      <div class="pb-field">
        <span class="pb-cap">API key</span>
        <div class="inputwrap">
          <input type="password" class="keyinput" data-p="${p}" placeholder="${k.set ? "•••••• stored — type to replace" : "paste key to enable " + PROV_LABEL[p]}" autocomplete="off" spellcheck="false">
          <button type="button" class="eye">Show</button>
        </div>
        <button type="button" class="linkbtn keyclear" data-p="${p}" ${k.set || pending ? "" : "hidden"}>Clear key</button>
      </div>
      <div class="pb-field">
        <span class="pb-cap">Model <button type="button" class="linkbtn modelfetch" data-p="${p}">refresh</button></span>
        <input class="modelinput" data-p="${p}" list="ml_${p}" value="${esc(currentModel(p))}" placeholder="default · ${esc(def)}" autocomplete="off" spellcheck="false">
        <datalist id="ml_${p}">${opts}</datalist>
      </div>
    </div>`;

  $("keyRows").querySelectorAll(".keyinput").forEach(inp => inp.oninput = () => {
    const p = inp.dataset.p;
    if (inp.value.trim()) pendingKeys[p] = inp.value.trim();
    else delete pendingKeys[p];
    $("settingsGate").hidden = anyKeySet();
  });
  $("keyRows").querySelectorAll(".eye").forEach(btn => btn.onclick = () => {
    const inp = btn.parentElement.querySelector(".keyinput");
    const reveal = inp.type === "password";
    inp.type = reveal ? "text" : "password";
    btn.textContent = reveal ? "Hide" : "Show";
  });
  $("keyRows").querySelectorAll(".keyclear").forEach(btn => btn.onclick = () => {
    pendingKeys[btn.dataset.p] = null; renderSettings();
  });
  $("keyRows").querySelectorAll(".modelinput").forEach(inp => inp.oninput = () => {
    pendingModels[inp.dataset.p] = inp.value.trim();
  });
  $("keyRows").querySelectorAll(".modelfetch").forEach(btn => btn.onclick = () => fetchModels(btn.dataset.p, btn));
}

$("saveSettings").onclick = async () => {
  const btn = $("saveSettings"); btn.disabled = true;
  const out = $("settingsOut"); out.innerHTML = "";
  try {
    const body = { provider: pendingProvider, keys: {}, models: {} };
    for (const p in pendingKeys) body.keys[p] = pendingKeys[p];
    for (const p in pendingModels) body.models[p] = pendingModels[p];
    settings = await api("/api/settings", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    for (const k in pendingKeys) delete pendingKeys[k];
    for (const k in pendingModels) delete pendingModels[k];
    pendingProvider = settings.provider || pendingProvider;
    renderSettings();
    $("settingsGate").hidden = anyKeySet();
    out.innerHTML = `<div class="ok">✓ saved</div>`;
    loadProvider();
    refreshModelSelect();
    // refresh live model list for the active provider now its key is stored
    if (settings.keys?.[pendingProvider]?.set) fetchModels(pendingProvider);
    setTimeout(() => { out.innerHTML = ""; }, 2500);
  } catch (e) { out.innerHTML = `<div class="err">✗ ${esc(e.message)}</div>`; }
  btn.disabled = false;
};

/* ---------- signup ---------- */
$("signup").onclick = async () => {
  const btn = $("signup"); btn.disabled = true; btn.querySelector("span").textContent = "Computing…";
  const out = $("signupOut"); out.innerHTML = "";
  try {
    const body = ["name", "dob", "tob", "pob", "tz", "lat", "lon"].reduce((o, k) => (o[k] = $(k).value.trim(), o), {});
    const r = await api("/api/signup", { method: "POST", body: JSON.stringify(body) });
    setUser(r.user_id);
    const s = r.summary;
    out.innerHTML = `<div class="ok">✓ chart computed · <code>${r.user_id.slice(0, 10)}…</code></div>
      <div class="kv" style="margin-top:9px">
        <span>Lagna</span><b>${s.lagna} (${s.lagna_degree}°)</b>
        <span>Moon</span><b>${s.moon}</b><span>Dasha</span><b>${s.dasha}</b></div>
      <div style="margin-top:8px">${s.yogas.map(y => `<span class="tag">${y}</span>`).join("")}</div>`;
    $("msg").focus();                       // ready to chat — jump the user to the composer
  } catch (e) { out.innerHTML = `<div class="err">✗ ${e.message}</div>`; }
  btn.disabled = false; btn.querySelector("span").textContent = "Compute chart";
};

/* ---------- full chart view ---------- */
$("chartBtn").onclick = async () => {
  const out = $("chartOut");
  if (!currentUser) return void (out.innerHTML = `<div class="err">No user selected.</div>`);
  out.innerHTML = `<div class="muted">Loading…</div>`;
  try {
    const c = await api(`/api/chart?user=${encodeURIComponent(currentUser)}`);
    const rows = ["Sun","Moon","Mars","Mercury","Jupiter","Venus","Saturn","Rahu","Ketu"].map(n => {
      const p = c.planets[n];
      return `<tr><td>${n}</td><td>${p.sign}</td><td>${p.house}H</td><td>${p.nakshatra} P${p.pada}</td><td>${p.retrograde?"℞":""}${p.combust?"☀":""}</td></tr>`;
    }).join("");
    const d = c.dashas;
    out.innerHTML = `<div class="kv"><span>Lagna</span><b>${c.lagna.sign} ${c.lagna.degree}° · ${c.lagna.lord}</b>
      <span>Atma / Amatya</span><b>${c.special_factors.atmakaraka} / ${c.special_factors.amatyakaraka}</b></div>
      <table><thead><tr><th>Planet</th><th>Sign</th><th>Hse</th><th>Nakshatra</th><th></th></tr></thead><tbody>${rows}</tbody></table>
      <div class="kv" style="margin-top:9px"><span>MD→AD→PD</span><b>${d.current_MD.planet} → ${d.current_AD.planet} → ${d.current_PD.planet}</b>
      <span>PD window</span><b>${d.current_PD.start} → ${d.current_PD.end}</b></div>
      <div style="margin-top:9px">${c.yogas.map(y => `<span class="tag" title="${esc(y.formed_by)}">${y.name}</span>`).join("")}</div>`;
  } catch (e) { out.innerHTML = `<div class="err">✗ ${e.message}</div>`; }
};

/* ---------- chat with streaming ---------- */
const STAGES = [["classifying","Reading"],["planning","Planning"],["writing","Writing"],["reviewing","Reviewing"]];

function userBubble(text) {
  const m = document.createElement("div"); m.className = "msg you";
  m.innerHTML = `<div class="avatar">🧑</div><div class="bubble">${esc(text)}</div>`;
  $("chat").appendChild(m); scrollChat();
}

function sageShell() {
  const m = document.createElement("div"); m.className = "msg sage";
  m.innerHTML = `<div class="avatar">✦</div><div class="bubble">
    <div class="stages">${STAGES.map(([k,l]) => `<span class="stage" data-k="${k}"><span class="sdot"></span>${l}</span>`).join("")}
      <span class="elapsed muted"></span></div>
    <div class="metaline" style="display:none"></div>
    <div class="body"><span class="typing"><i></i><i></i><i></i></span> <span class="think muted">reading your chart…</span></div></div>`;
  $("chat").appendChild(m); scrollChat();
  return m;
}
const STAGE_LABEL = { classifying: "reading your chart…", planning: "choosing the reading angle…", writing: "composing your reading…", reviewing: "reviewing for quality…" };

/* Auto-scroll only while the user is pinned to the bottom; if they scroll up to
   re-read, don't yank them down — surface a "jump to latest" button instead. */
let pinned = true;
function scrollChat(force) {
  const chat = $("chat");
  if (force || pinned) { chat.scrollTop = chat.scrollHeight; pinned = true; $("jumpLatest").hidden = true; }
  else { $("jumpLatest").hidden = chat.children.length === 0; }
}
$("chat").addEventListener("scroll", () => {
  const chat = $("chat");
  pinned = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 48;
  if (pinned) $("jumpLatest").hidden = true;
});
$("jumpLatest").onclick = () => scrollChat(true);

function markStage(shell, key) {
  let reached = false;
  shell.querySelectorAll(".stage").forEach(el => {
    if (el.dataset.k === key) { el.classList.add("active"); el.classList.remove("done"); reached = true; }
    else if (!reached) { el.classList.remove("active"); el.classList.add("done"); }
  });
}

async function sendMessage(text) {
  if (!currentUser || sending) { updateChatGate(); return; }
  pinned = true;   // user just sent — follow the new reply
  setSending(true);
  userBubble(text);
  const shell = sageShell();
  const bodyEl = shell.querySelector(".body");
  const elapsedEl = shell.querySelector(".elapsed");
  const metaEl = shell.querySelector(".metaline");
  let acc = "", firstToken = false;
  const t0 = performance.now();
  const timer = setInterval(() => { elapsedEl.textContent = ((performance.now() - t0) / 1000).toFixed(1) + "s"; }, 100);

  const render = () => { bodyEl.innerHTML = esc(acc) + `<span class="caret"></span>`; scrollChat(); };

  const onEvent = (kind, data) => {
    if (kind === "stage") {
      markStage(shell, data.stage);
      if (!firstToken) { const th = shell.querySelector(".think"); if (th) th.textContent = STAGE_LABEL[data.stage] || data.detail || ""; }
    }
    else if (kind === "meta") {
      const bits = [];
      if (data.domain) bits.push(`<span class="b">${data.domain}</span>`);
      if (data.mechanism) bits.push(`mechanism: ${data.mechanism}`);
      if (data.insight_axis) bits.push(`axis: ${data.insight_axis}`);
      if (data.intent) bits.push(data.intent);
      if (bits.length) { metaEl.innerHTML = bits.join(" · "); metaEl.style.display = "flex"; }
    } else if (kind === "token") {
      if (!firstToken) { firstToken = true; bodyEl.innerHTML = ""; }
      acc += data.text; render();
    } else if (kind === "done") {
      clearInterval(timer);
      shell.querySelectorAll(".stage").forEach(el => { el.classList.remove("active"); el.classList.add("done"); });
      bodyEl.innerHTML = esc(acc);
      const secs = ((performance.now() - t0) / 1000).toFixed(1);
      metaEl.innerHTML += `${metaEl.textContent ? " · " : ""}<span class="muted">${data.provider} · ${secs}s</span>`;
      metaEl.style.display = "flex";
    } else if (kind === "error") {
      clearInterval(timer);
      const friendly = /no chart/i.test(data.error)
        ? "This chart has no computed data yet — compute it on the left first."
        : data.error;
      bodyEl.innerHTML = `<span class="err">⚠ ${esc(friendly)}</span>`;
      shell.querySelector(".stages").style.display = "none";
    }
  };

  try {
    const resp = await fetch("/api/chat/stream", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: currentUser, session, message: text, provider: $("provSel").value }),
    });
    if (!resp.ok || !resp.body) throw new Error("HTTP " + resp.status);
    const reader = resp.body.getReader(); const dec = new TextDecoder(); let buf = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, i); buf = buf.slice(i + 2);
        let ev = "message", dt = "";
        for (const line of raw.split("\n")) {
          if (line.startsWith("event:")) ev = line.slice(6).trim();
          else if (line.startsWith("data:")) dt += line.slice(5).trim();
        }
        if (dt) onEvent(ev, JSON.parse(dt));
      }
    }
  } catch (e) { clearInterval(timer); bodyEl.innerHTML = `<span class="err">⚠ ${esc(e.message)}</span>`; }
  finally { setSending(false); $("msg").focus(); }
}

$("chatForm").onsubmit = (e) => { e.preventDefault(); const v = $("msg").value.trim(); if (v) { sendMessage(v); $("msg").value = ""; updateSendState(); } };
$("msg").addEventListener("input", updateSendState);
document.querySelectorAll(".chip").forEach(c => c.onclick = () => { if (!c.disabled) sendMessage(c.dataset.q); });

async function validateStoredUser() {
  if (!currentUser) return;
  try {
    const r = await fetch(`/api/chart?user=${encodeURIComponent(currentUser)}`);
    if (!r.ok) setUser("");          // stale id from a previous DB — drop it silently
  } catch { /* offline — leave as is */ }
}

setUser(currentUser);
validateStoredUser();
loadProvider();
refreshModelSelect();

/* By default, open the Model & API-key popup until at least one key is configured. */
(async function ensureConfigured() {
  try {
    const s = await api("/api/settings");
    const hasKey = Object.values(s.keys || {}).some(k => k.set);
    if (!hasKey) openSettings();
  } catch { /* offline */ }
})();
