const $ = (id) => document.getElementById(id);
const esc = (s) => s.replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

const api = async (path, opts) => {
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({ error: "bad JSON from server" }));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
};

let currentUser = localStorage.getItem("starsage_user") || "";
const session = "web-" + Math.random().toString(36).slice(2, 8);

function setUser(id) {
  currentUser = id;
  localStorage.setItem("starsage_user", id);
  $("activeUser").textContent = id ? `· ${id.slice(0, 8)}…` : "";
}

async function loadProvider() {
  try {
    const p = await api("/api/provider");
    const keys = Object.entries(p.keys).filter(([, v]) => v).map(([k]) => k).join(", ") || "none · mock";
    $("provider").innerHTML = `<span class="dot"></span> ${p.provider} · keys: ${keys}`;
    $("provider").classList.add("live");
  } catch { $("provider").innerHTML = `<span class="dot"></span> offline`; }
}

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
    $("loadUser").value = r.user_id;
  } catch (e) { out.innerHTML = `<div class="err">✗ ${e.message}</div>`; }
  btn.disabled = false; btn.querySelector("span").textContent = "Compute chart";
};

/* ---------- chart ---------- */
$("loadBtn").onclick = () => { const id = $("loadUser").value.trim(); if (id) { setUser(id); $("chartOut").innerHTML = `<div class="ok">Loaded ${id.slice(0,8)}…</div>`; } };
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
const scrollChat = () => { $("chat").scrollTop = $("chat").scrollHeight; };

function markStage(shell, key) {
  let reached = false;
  shell.querySelectorAll(".stage").forEach(el => {
    if (el.dataset.k === key) { el.classList.add("active"); el.classList.remove("done"); reached = true; }
    else if (!reached) { el.classList.remove("active"); el.classList.add("done"); }
  });
}

async function sendMessage(text) {
  if (!currentUser) { const s = sageShell(); s.querySelector(".body").innerHTML = `<span class="err">Create or load a user first (panel 1).</span>`; s.querySelector(".stages").remove(); return; }
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
        ? "This user has no computed chart. Fill panel 1 and click “Compute chart” first."
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
}

$("chatForm").onsubmit = (e) => { e.preventDefault(); const v = $("msg").value.trim(); if (v) { sendMessage(v); $("msg").value = ""; } };
document.querySelectorAll(".chip").forEach(c => c.onclick = () => sendMessage(c.dataset.q));

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
