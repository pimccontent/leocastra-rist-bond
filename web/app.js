const app = document.getElementById("app");
const pill = document.getElementById("bondPill");
const pillText = document.getElementById("bondPillText");

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function toast(message, kind) {
  const host = document.getElementById("toasts");
  host.hidden = false;
  host.innerHTML = `<div class="toast ${kind || "ok"}">${esc(message)}</div>`;
  setTimeout(() => {
    host.hidden = true;
  }, 3200);
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) throw new Error(`${response.status}`);
  return response.json();
}

function route() {
  const hash = location.hash || "#/";
  return hash === "#/settings" ? "settings" : hash === "#/help" ? "help" : "status";
}

function setNav(name) {
  for (const id of ["status", "settings", "help"]) {
    document.getElementById(`nav-${id}`).classList.toggle("active", id === name);
  }
}

function encoderUrls(status) {
  const host = status.lanIp && status.lanIp !== "127.0.0.1" ? status.lanIp : "127.0.0.1";
  const port = status.listenPort || 4011;
  const obs = `srt://${host}:${port}?mode=caller&latency=200000&pkt_size=1316&transtype=live`;
  const vmix = `srt://${host}:${port}?mode=caller&latency=200&pkt_size=1316`;
  return { obs, vmix };
}

function renderStatus(status) {
  const bond = status.bond || {};
  const sending = Boolean(bond.sender && bond.ffmpeg);
  const kind = sending ? "ok" : status.paths.length ? "wait" : "down";
  const bondLabel = sending ? "Live" : status.paths.length ? "Waiting" : "Idle";
  pill.className = `pill ${kind}`;
  pillText.textContent = bondLabel.toUpperCase();
  const pathRows = (status.paths || [])
    .map((path, index) => {
      const port = (status.linkPorts && status.linkPorts[index]) || Number(status.basePort) + index;
      return `<tr><td>${esc(path.iface)}</td><td><code>${esc(path.address)}</code></td><td><code>${esc(status.studioHost || "—")}:${port}</code></td><td class="state ${path.up ? "ok" : "wait"}">${path.up ? "Up" : "Waiting"}</td></tr>`;
    })
    .join("") || '<tr><td colspan="4" class="muted">Waiting for a modem or Wi-Fi uplink</td></tr>';
  const netRows = (status.networks || [])
    .map((net) => {
      const role = net.kind === "ethernet" ? "LAN" : net.bondable ? "Uplink" : "Other";
      return `<tr><td>${esc(net.iface)}</td><td><code>${esc(net.address || "—")}</code></td><td>${esc(role)}</td><td class="state ${net.up ? "ok" : "down"}">${net.up ? "Up" : "Down"}</td></tr>`;
    })
    .join("") || '<tr><td colspan="4" class="muted">No interfaces reported</td></tr>';
  const urls = encoderUrls(status);
  return `
    <div class="grid">
      <div class="card"><h2>Input</h2><div class="metric ${bond.ffmpeg ? "ok" : "wait"}">${bond.ffmpeg ? "Listening" : "Offline"}</div><p class="hint">OBS SRT into this kit</p></div>
      <div class="card"><h2>Bond</h2><div class="metric ${kind}">${esc(bondLabel)}</div><p class="hint">${esc(bond.note || "No links yet")}</p></div>
      <div class="card"><h2>Links</h2><div class="metric ${status.paths.length ? "ok" : "down"}">${status.paths.length}</div><p class="hint">${esc(status.mode)} · ${esc(status.bufferMs)} ms ceiling</p></div>
      <div class="card"><h2>Profile</h2><div class="metric">Main</div><p class="hint">${status.encryption ? `AES-${status.encryption}` : "Encryption off"}</p></div>
    </div>
    <section class="card section">
      <h2>Encoder</h2>
      <p class="hint">OBS: Settings, Stream, Service Custom. Paste the OBS URL into Server and leave the stream key empty. vMix uses the millisecond URL. Ethernet on this kit stays the encoder LAN.</p>
      <div class="copy-row"><input id="encoderObs" class="copy-target" readonly value="${esc(urls.obs)}"/><button type="button" class="ghost" id="copyObs">Copy OBS</button></div>
      <div class="copy-row"><input id="encoderVmix" class="copy-target" readonly value="${esc(urls.vmix)}"/><button type="button" class="ghost" id="copyVmix">Copy vMix</button></div>
    </section>
    <div class="section card">
      <h2>Links</h2>
      <div class="table-wrap"><table><thead><tr><th>Interface</th><th>Address</th><th>Studio</th><th>State</th></tr></thead><tbody>${pathRows}</tbody></table></div>
    </div>
    <div class="section card">
      <h2>Networks</h2>
      <div class="table-wrap"><table><thead><tr><th>Interface</th><th>Address</th><th>Role</th><th>Link</th></tr></thead><tbody>${netRows}</tbody></table></div>
      <p class="hint section">Ethernet is the OBS LAN. USB modems and Wi-Fi carry the bond. A private 192.168 address on a modem is normal.</p>
    </div>`;
}

function renderSettings(cfg, status) {
  const uplinks = (status.networks || []).filter((net) => net.bondable);
  const chosen = new Set(cfg.paths || []);
  const boxes = uplinks.length
    ? uplinks.map((net) => `<label class="choice"><input type="checkbox" name="path" value="${esc(net.iface)}" ${chosen.has(net.iface) ? "checked" : ""}/> <span>${esc(net.iface)} · ${esc(net.address || "no address")}</span></label>`).join("")
    : `<p class="hint">No modem or Wi-Fi interface is visible.</p>`;
  return `
    <form id="settingsForm" class="settings-grid">
      <section class="card">
        <h2>LeoCastra</h2>
        <div class="field"><label class="label-row">Link lines from the RIST stream</label><textarea name="studioUrls" rows="4" placeholder="rist://studio.example:18180?...&#10;rist://studio.example:18181?...">${esc(cfg.studioUrls || "")}</textarea></div>
        <p class="hint">In LeoCastra, set Bond links to the number of modems, save, and paste every line here. Each line is one door for the same OBS feed.</p>
        <div class="field"><label class="label-row">Studio host</label><input name="studioHost" value="${esc(cfg.studioHost)}" placeholder="Filled from the link lines"/></div>
        <div class="field"><label class="label-row">First link port</label><input name="basePort" type="number" min="1" max="65535" value="${esc(cfg.basePort)}"/></div>
        <div class="field"><label class="label-row">Recovery ceiling (ms)</label><input name="bufferMs" type="number" min="200" max="8000" value="${esc(cfg.bufferMs)}"/></div>
        <p class="hint">Pasting the lines fills the host, ports, ceiling, and passphrase. 200 ms stays fixed. A higher value is the ceiling.</p>
      </section>
      <section class="card">
        <h2>This kit</h2>
        <div class="field"><label class="label-row">Encoder SRT port</label><input name="listenPort" type="number" min="1" max="65535" value="${esc(cfg.listenPort)}"/></div>
        <div class="field"><label class="label-row">Bond mode</label>
          <select name="mode">
            <option value="seamless" ${cfg.mode !== "split" ? "selected" : ""}>Seamless (full copy on each path)</option>
            <option value="split" ${cfg.mode === "split" ? "selected" : ""}>Split (share packets across paths)</option>
          </select>
        </div>
        <div class="field"><label class="label-row">Encryption</label>
          <select name="encryption">
            <option value="0" ${Number(cfg.encryption) === 0 ? "selected" : ""}>Off</option>
            <option value="128" ${Number(cfg.encryption) === 128 ? "selected" : ""}>AES-128</option>
            <option value="256" ${Number(cfg.encryption) === 256 ? "selected" : ""}>AES-256</option>
          </select>
        </div>
        <div class="field"><label class="label-row">Passphrase ${cfg.secretSet ? "(saved — type to replace)" : ""}</label><input name="secret" type="password" autocomplete="new-password"/></div>
      </section>
      <section class="card span-all">
        <h2>Paths</h2>
        <div class="field"><label class="label-row">Uplink mode</label>
          <select name="uplinkMode" id="uplinkMode">
            <option value="auto" ${cfg.uplinkMode !== "manual" ? "selected" : ""}>Auto (every modem and Wi-Fi with an address)</option>
            <option value="manual" ${cfg.uplinkMode === "manual" ? "selected" : ""}>Manual</option>
          </select>
        </div>
        <div id="manualPaths" class="${cfg.uplinkMode === "manual" ? "" : "is-hidden"}">${boxes}</div>
      </section>
      <section class="card apply-card span-all">
        <h2>Apply</h2>
        <p class="apply-copy">Save sends this one feed through the selected modems and reconnects to LeoCastra. Stopping OBS leaves those links up.</p>
        <div class="actions">
          <button class="primary" type="submit">Save and reconnect</button>
          <button class="ghost" type="button" id="restartOnly">Reconnect now</button>
        </div>
      </section>
    </form>`;
}

function renderHelp() {
  return `
    <section class="help-hero card">
      <h2>RIST bond kit</h2>
      <p>OBS or vMix sends one SRT stream to this Ubuntu kit. The kit carries that same feed on one modem per LeoCastra link line. Ethernet stays the encoder LAN. Field OB SRTLA is a separate bond.</p>
    </section>
    <div class="help-grid">
      <article class="help-card card"><h3>Encoder</h3><p>Copy the OBS URL from Status. Service Custom, URL in Server, empty stream key. The local hop is 200 ms. The kit does not transcode.</p></article>
      <article class="help-card card"><h3>Paths</h3><p>Seamless sends a full copy on every path. Split shares packets and needs every path to stay up. Each path uses the next UDP port after the first.</p></article>
      <article class="help-card card"><h3>LeoCastra</h3><p>Set Bond links on the RIST stream to the number of modems, save, and paste every link line into Settings. LeoCastra joins those links back into one feed, then ingests it or relays it to the MCR.</p></article>
    </div>
    <section class="help-steps card">
      <h2>First setup</h2>
      <ol>
        <li>Install on Ubuntu 24.04 with host networking so each modem keeps its own address.</li>
        <li>Open this page from a laptop on the kit LAN.</li>
        <li>In LeoCastra, set Bond links to 2 for two modems, save, and copy both link lines.</li>
        <li>Paste both lines into Settings. Leave uplink mode on Auto. Ethernet will not be bonded.</li>
        <li>Save and reconnect, then start the encoder.</li>
      </ol>
    </section>`;
}

let drawSeq = 0;
async function draw() {
  const seq = ++drawSeq;
  const name = route();
  setNav(name);
  if (name === "help") {
    app.innerHTML = renderHelp();
    return;
  }
  const status = await api("/api/status");
  if (seq !== drawSeq) return;
  if (name === "settings") {
    const cfg = await api("/api/config");
    app.innerHTML = renderSettings(cfg, status);
    document.getElementById("uplinkMode").addEventListener("change", (event) => {
      document.getElementById("manualPaths").classList.toggle("is-hidden", event.target.value !== "manual");
    });
    document.getElementById("settingsForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(event.target);
      const payload = {
        studioUrls: String(form.get("studioUrls") || "").trim(),
        studioHost: String(form.get("studioHost") || "").trim(),
        basePort: Number(form.get("basePort")),
        bufferMs: Number(form.get("bufferMs")),
        listenPort: Number(form.get("listenPort")),
        mode: form.get("mode"),
        uplinkMode: form.get("uplinkMode"),
        encryption: Number(form.get("encryption")),
        paths: form.getAll("path"),
      };
      const secret = String(form.get("secret") || "");
      if (secret) payload.secret = secret;
      try {
        const saved = await api("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        toast(saved.note || "Saved");
        if (saved.ok !== false) location.hash = "#/";
      } catch (error) {
        toast("Could not save settings", "err");
      }
    });
    document.getElementById("restartOnly").addEventListener("click", async () => {
      const next = await api("/api/restart", { method: "POST" });
      toast(next.bond.note || "Reconnected");
    });
    return;
  }
  app.innerHTML = renderStatus(status);
  for (const [id, input] of [["copyObs", "encoderObs"], ["copyVmix", "encoderVmix"]]) {
    document.getElementById(id).addEventListener("click", async () => {
      await navigator.clipboard.writeText(document.getElementById(input).value);
      toast("Copied");
    });
  }
}

window.addEventListener("hashchange", () => draw().catch((error) => toast(error.message, "err")));
draw().catch((error) => {
  app.textContent = error.message;
});
setInterval(() => {
  if (route() === "status") draw().catch(() => {});
}, 4000);
