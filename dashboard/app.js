/**
 * Dashboard MQTT Client — Tenuta Ferrante
 * Ref: UC-05, RI-03, plan.md (Prototipo Minimo)
 *
 * Connessione MQTT over WebSocket (porta 8083) per:
 *  - Visualizzazione real-time microclima 12 parcelle (UC-01)
 *  - Grafici storici per parcella (Chart.js)
 *  - Invio comandi irrigazione (UC-03)
 *  - Ricezione alert (UC-06)
 */

// ── Config ───────────────────────────────────────────────────────────

const BROKER_URL = `ws://${location.hostname || "localhost"}:8083/mqtt`;
const INFLUXDB_URL = `/api/influxdb`;
const INFLUXDB_TOKEN = "dev-token-tenuta-ferrante";
const INFLUXDB_ORG = "tenuta-ferrante";
const INFLUXDB_BUCKET = "sensori";

const PARCELLE = [
  { id: "vigna_alta_01",  nome: "Vigna Alta 1",  zona: "alta",  altitudine: 590, vitigno: "Aglianico" },
  { id: "vigna_alta_02",  nome: "Vigna Alta 2",  zona: "alta",  altitudine: 570, vitigno: "Aglianico" },
  { id: "vigna_alta_03",  nome: "Vigna Alta 3",  zona: "alta",  altitudine: 555, vitigno: "Aglianico" },
  { id: "vigna_alta_04",  nome: "Vigna Alta 4",  zona: "alta",  altitudine: 560, vitigno: "Moscato" },
  { id: "vigna_media_01", nome: "Vigna Media 1", zona: "media", altitudine: 520, vitigno: "Aglianico" },
  { id: "vigna_media_02", nome: "Vigna Media 2", zona: "media", altitudine: 500, vitigno: "Malvasia" },
  { id: "vigna_media_03", nome: "Vigna Media 3", zona: "media", altitudine: 480, vitigno: "Aglianico" },
  { id: "vigna_media_04", nome: "Vigna Media 4", zona: "media", altitudine: 460, vitigno: "Malvasia" },
  { id: "vigna_bassa_01", nome: "Vigna Bassa 1", zona: "bassa", altitudine: 440, vitigno: "Aglianico" },
  { id: "vigna_bassa_02", nome: "Vigna Bassa 2", zona: "bassa", altitudine: 430, vitigno: "Moscato" },
  { id: "vigna_bassa_03", nome: "Vigna Bassa 3", zona: "bassa", altitudine: 415, vitigno: "Aglianico" },
  { id: "vigna_bassa_04", nome: "Vigna Bassa 4", zona: "bassa", altitudine: 405, vitigno: "Malvasia" },
];

const SENSOR_TYPES = ["temperatura", "umidita", "vento", "direzione_vento", "pioggia", "radiazione"];
const SENSOR_LABELS = {
  temperatura: "Temp",
  umidita: "Umid",
  vento: "Vento",
  direzione_vento: "Dir.V",
  pioggia: "Pioggia",
  radiazione: "Sole",
};
const CHART_COLORS = {
  temperatura: "#f87171",
  umidita: "#4f8cff",
  vento: "#34d399",
  direzione_vento: "#a78bfa",
  pioggia: "#fbbf24",
  radiazione: "#f59e0b",
};
const SENSOR_UNITS = {
  temperatura: "°C",
  umidita: "%",
  vento: "km/h",
  direzione_vento: "°",
  pioggia: "mm",
  radiazione: "W/m²",
};
const MAX_CHART_POINTS = 360;
const CHART_POINTS_BY_RANGE = {
  "5m":  60,
  "15m": 90,
  "1h":  120,
  "6h":  180,
  "24h": 288,
};

// ── State ────────────────────────────────────────────────────────────

const state = {
  connected: false,
  messageCount: 0,
  commandCount: 0,
  sensors: {},          // { "vigna_alta_01/temperatura": { value, unit, timestamp } }
  sensorLastSeen: {},   // { "vigna_alta_01/temperatura": Date.now() }
  valves: {},           // { "vigna_alta_01": { status, lastUpdate } }
  activeAlerts: new Map(),  // chiave "parcella|tipo" → oggetto alert attivo
  alertHistory: [],         // alert risolti, max 100
  alertTab: "attivi",       // tab corrente: "attivi" | "storico"
  activeSensors: new Set(),
  selectedParcella: null,
  activeZone: "tutte",
  // Time-series for charts: { "vigna_alta_01": { temperatura: [{t, v}...], ... } }
  history: {},
};

let client = null;
let charts = {};

// ── DOM refs ─────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);
const $connectionBadge = $("connection-badge");
const $connectionText = $("connection-text");
const $statMessages = $("stat-messages");
const $statSensors = $("stat-sensors");
const $statOffline = $("stat-offline");
const $statCommands = $("stat-commands");
const $statAlerts = $("stat-alerts");
const $parcelleGrid = $("parcelle-grid");
const $valvesList = $("valves-list");
const $logPanel = $("log-panel");
const $detailPanel = $("detail-panel");
const $detailTitle = $("detail-title");
const $detailSubtitle = $("detail-subtitle");

// ── Init UI ──────────────────────────────────────────────────────────

function initUI() {
  PARCELLE.forEach((p) => {
    // Init history
    state.history[p.id] = {};
    SENSOR_TYPES.forEach((s) => { state.history[p.id][s] = []; });

    // Parcella card
    const card = document.createElement("div");
    card.className = "parcella-card";
    card.id = `card-${p.id}`;
    card.dataset.zona = p.zona;
    card.onclick = () => selectParcella(p.id);
    card.innerHTML = `
      <div class="parcella-header">
        <div class="parcella-info">
          <span class="parcella-name">${p.nome}</span>
          <span class="parcella-meta">${p.vitigno} · ${p.altitudine}m</span>
        </div>
        <span class="parcella-badge offline" id="badge-${p.id}">Offline</span>
      </div>
      <div class="sensor-grid">
        ${SENSOR_TYPES.map((s) => `
          <div class="sensor-cell" id="cell-${p.id}-${s}">
            <span class="sensor-label">${SENSOR_LABELS[s]}</span>
            <span class="sensor-value" id="val-${p.id}-${s}">--</span>
          </div>`).join("")}
      </div>`;
    $parcelleGrid.appendChild(card);

    // Valve row
    const row = document.createElement("div");
    row.className = "valve-row";
    row.innerHTML = `
      <div class="valve-info">
        <span class="valve-name">${p.nome}</span>
        <span class="valve-status chiusa" id="vstatus-${p.id}">chiusa</span>
      </div>
      <div class="valve-actions">
        <button class="btn btn-open" id="btn-open-${p.id}" onclick="sendIrrigationCmd('${p.id}', 'apri')">Apri</button>
        <button class="btn btn-close" id="btn-close-${p.id}" onclick="sendIrrigationCmd('${p.id}', 'chiudi')">Chiudi</button>
      </div>`;
    $valvesList.appendChild(row);
    state.valves[p.id] = { status: "chiusa", lastUpdate: null };
  });

  initCharts();
}

// ── Chart.js Setup ───────────────────────────────────────────────────

function initCharts() {
  const baseOpts = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 0 },
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (items) => {
            const d = new Date(items[0].parsed.x);
            return d.toLocaleString("it-IT", {
              day: "2-digit", month: "2-digit",
              hour: "2-digit", minute: "2-digit", second: "2-digit",
            });
          },
          label: (item) => {
            const unit = SENSOR_UNITS[item.dataset.label] ?? "";
            return `${item.parsed.y.toFixed(1)} ${unit}`;
          },
        },
      },
    },
    scales: {
      x: {
        type: "linear",
        display: true,
        ticks: {
          color: "#636a7e",
          font: { size: 10 },
          callback: (v) => {
            const d = new Date(v);
            return d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
          },
          maxTicksLimit: 6,
        },
        grid: { color: "rgba(45, 49, 66, 0.5)" },
      },
      y: {
        display: true,
        ticks: { color: "#636a7e", font: { size: 10 } },
        grid: { color: "rgba(45, 49, 66, 0.5)" },
      },
    },
  };

  SENSOR_TYPES.forEach((tipo) => {
    const ctx = $(`chart-${tipo}`).getContext("2d");
    charts[tipo] = new Chart(ctx, {
      type: "line",
      data: {
        datasets: [{
          label: tipo,
          data: [],
          borderColor: CHART_COLORS[tipo],
          backgroundColor: CHART_COLORS[tipo] + "20",
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          fill: true,
          tension: 0.3,
          segment: {
            borderColor: (ctx) => ctx.p1.parsed.x - ctx.p0.parsed.x > charts._maxGap ? "transparent" : undefined,
            backgroundColor: (ctx) => ctx.p1.parsed.x - ctx.p0.parsed.x > charts._maxGap ? "transparent" : undefined,
          },
        }],
      },
      options: { ...baseOpts },
    });
  });
}

const RANGE_MS = { "5m": 5*60e3, "15m": 15*60e3, "1h": 3600e3, "6h": 6*3600e3, "24h": 24*3600e3 };
// Inizializzato in updateCharts(), usato da segment callback per spezzare la linea sui gap
charts._maxGap = 3600e3 * 0.05;

function updateCharts(parcellaId) {
  if (!state.history[parcellaId]) return;

  let xMin, xMax;
  if (historyRange === "custom" && customFrom && customTo) {
    xMin = customFrom;
    xMax = customTo;
  } else {
    const now = Date.now();
    const rangeMs = RANGE_MS[historyRange] || 3600e3;
    xMin = now - rangeMs;
    xMax = now;
  }

  const spanMs = xMax - xMin;
  // Gap > 5% del range visibile → spezza la linea
  charts._maxGap = spanMs * 0.05;

  // Formato tick adatto al range
  const useSeconds = spanMs <= 15 * 60e3;
  const tickCallback = useSeconds
    ? (v) => new Date(v).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : (v) => new Date(v).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });

  // Se tutti i dati sono concentrati alla fine del range, zoom sul dato reale
  // (aggiunge 2% di padding prima del primo punto; non va mai prima di xMin)
  let earliestT = xMax;
  SENSOR_TYPES.forEach((tipo) => {
    const d = state.history[parcellaId][tipo];
    if (d.length > 0) earliestT = Math.min(earliestT, d[0].t);
  });
  const effectiveXMin = (earliestT > xMin)
    ? Math.max(xMin, earliestT - spanMs * 0.02)
    : xMin;

  SENSOR_TYPES.forEach((tipo) => {
    const data = state.history[parcellaId][tipo];
    charts[tipo].data.datasets[0].data = data.map((d) => ({ x: d.t, y: d.v }));
    charts[tipo].options.scales.x.min = effectiveXMin;
    charts[tipo].options.scales.x.max = xMax;
    charts[tipo].options.scales.x.ticks.callback = tickCallback;
    charts[tipo].update("none");
  });
}

// ── Parcella Selection ───────────────────────────────────────────────

function selectParcella(id) {
  // Toggle off if already selected
  if (state.selectedParcella === id) {
    closeDetail();
    return;
  }

  state.selectedParcella = id;
  const p = PARCELLE.find((x) => x.id === id);

  // Highlight card
  document.querySelectorAll(".parcella-card").forEach((c) => c.classList.remove("selected"));
  $(`card-${id}`).classList.add("selected");

  // Show detail panel
  $detailTitle.textContent = p.nome;
  $detailSubtitle.textContent = `${p.vitigno} · ${p.zona} · ${p.altitudine}m slm`;
  $detailPanel.classList.add("visible");

  updateCharts(id);
}

function closeDetail() {
  state.selectedParcella = null;
  $detailPanel.classList.remove("visible");
  document.querySelectorAll(".parcella-card").forEach((c) => c.classList.remove("selected"));
}

// ── Zone Filter ──────────────────────────────────────────────────────

function filterZone(zona) {
  state.activeZone = zona;
  document.querySelectorAll(".zone-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.zone === zona);
  });

  document.querySelectorAll(".parcella-card").forEach((card) => {
    if (zona === "tutte" || card.dataset.zona === zona) {
      card.style.display = "";
    } else {
      card.style.display = "none";
    }
  });
}

// ── MQTT Connection ──────────────────────────────────────────────────

function connect() {
  log("SYS", "Connessione...", BROKER_URL);

  client = mqtt.connect(BROKER_URL, {
    clientId: `dashboard-${Date.now()}`,
    username: "dashboard",
    password: "dashboard123",
    reconnectPeriod: 3000,
    connectTimeout: 10000,
    protocolVersion: 5,
  });

  client.on("connect", () => {
    state.connected = true;
    updateConnectionUI();
    log("SYS", "Connesso al broker EMQX");

    client.subscribe("tenuta/parcella/+/microclima/#", { qos: 0 });
    client.subscribe("tenuta/parcella/+/suolo/#", { qos: 0 });
    client.subscribe("tenuta/parcella/+/irrigazione/stato", { qos: 1 });
    client.subscribe("tenuta/parcella/+/irrigazione/ack", { qos: 2 });
    client.subscribe("tenuta/alert/#", { qos: 1 });
  });

  client.on("close", () => {
    state.connected = false;
    updateConnectionUI();
    log("SYS", "Disconnesso");
  });

  client.on("error", (err) => {
    log("ERR", err.message);
  });

  client.on("message", (topic, message) => {
    state.messageCount++;

    let payload;
    try {
      payload = JSON.parse(message.toString());
    } catch {
      return;
    }

    const parts = topic.split("/");

    if (parts[3] === "microclima" && parts.length >= 5) {
      handleMicroclima(parts[2], parts[4], payload);
    } else if (parts[3] === "suolo" && parts.length >= 6) {
      handleSuolo(parts[2], parts[4], parts[5], payload);
    } else if (parts[3] === "irrigazione" && parts.length >= 5) {
      handleIrrigation(parts[2], parts[4], payload);
    } else if (parts[1] === "alert") {
      handleAlert(payload);
    }
  });
}

// ── Message Handlers ─────────────────────────────────────────────────

function handleMicroclima(parcella, tipo, payload) {
  const key = `${parcella}/${tipo}`;
  state.sensors[key] = {
    value: payload.value,
    unit: payload.unit,
    timestamp: payload.timestamp,
  };
  state.sensorLastSeen[key] = Date.now();
  state.activeSensors.add(key);
  updateSensorStats();

  // Update card value
  const $val = $(`val-${parcella}-${tipo}`);
  if ($val) {
    $val.textContent = `${payload.value}${payload.unit ? " " + payload.unit : ""}`;
    $val.classList.toggle("alert", tipo === "temperatura" && payload.value < 2);
  }
  const $cell = $(`cell-${parcella}-${tipo}`);
  if ($cell) {
    $cell.classList.remove("stale-warn", "stale-err");
  }

  // Badge online
  updateParcellaBadge(parcella);

  // Push to history for charts
  if (state.history[parcella] && state.history[parcella][tipo]) {
    const series = state.history[parcella][tipo];
    const t = payload.timestamp ? new Date(payload.timestamp).getTime() : Date.now();

    if (series.length === 0 || t >= series[series.length - 1].t) {
      series.push({ t, v: payload.value });
    } else {
      // Buffered data: insert in chronological order
      let i = series.length - 1;
      while (i > 0 && series[i - 1].t > t) i--;
      series.splice(i, 0, { t, v: payload.value });
    }
    if (series.length > MAX_CHART_POINTS) series.shift();

    // Live-update chart if this parcella is selected
    if (state.selectedParcella === parcella) {
      updateCharts(parcella);
    }
  }
}

function handleSuolo(parcella, profondita, tipo, payload) {
  const key = `${parcella}/suolo/${profondita}/${tipo}`;
  state.sensors[key] = {
    value: payload.value,
    unit: payload.unit,
    timestamp: payload.timestamp,
  };
  state.sensorLastSeen[key] = Date.now();
  state.activeSensors.add(key);
  updateSensorStats();
}

function handleIrrigation(parcella, subtopic, payload) {
  if (subtopic === "stato") {
    const status = payload.value;
    state.valves[parcella] = { status, lastUpdate: payload.timestamp };

    const $vstatus = $(`vstatus-${parcella}`);
    if ($vstatus) {
      $vstatus.textContent = status;
      $vstatus.className = `valve-status ${status}`;
    }

    const inProgress = status === "in_esecuzione";
    const $open = $(`btn-open-${parcella}`);
    const $close = $(`btn-close-${parcella}`);
    if ($open) $open.disabled = inProgress;
    if ($close) $close.disabled = inProgress;

    log("IRR", `${parcella} stato: ${status}`);
  } else if (subtopic === "ack") {
    log("ACK", `${parcella} ack: ${JSON.stringify(payload.value)}`);
  }
}

// Mappa tipo alert → campo valore e unità nel payload EMQX
const ALERT_VALUE_MAP = {
  gelata:         { field: "temperatura",   unit: "°C",   label: "Temperatura",  soglia: "2 °C" },
  vento:          { field: "vento_kmh",     unit: "km/h", label: "Vento",        soglia: "50 km/h" },
  stress_idrico:  { field: "tensione_kpa",  unit: "kPa",  label: "Tensione",     soglia: "80 kPa" },
};

function handleAlert(payload) {
  const parcella = payload.parcella || "sconosciuta";
  const tipo = payload.tipo || "sconosciuto";
  const key = `${parcella}|${tipo}`;
  const now = Date.now();

  const parcellaInfo = PARCELLE.find((p) => p.id === parcella);
  const parcellaName = parcellaInfo ? parcellaInfo.nome : parcella;
  const meta = ALERT_VALUE_MAP[tipo];
  const value = meta ? payload[meta.field] : null;
  const unit = meta ? meta.unit : "";

  if (state.activeAlerts.has(key)) {
    const existing = state.activeAlerts.get(key);
    existing.lastSeen = now;
    existing.count++;
    if (value != null) existing.value = value;
  } else {
    state.activeAlerts.set(key, {
      key,
      alert: payload.alert || "Alert",
      tipo,
      livello: payload.livello || "critico",
      parcella,
      parcellaName,
      messaggio: payload.messaggio || "",
      value,
      unit,
      firstSeen: now,
      lastSeen: now,
      count: 1,
    });
    log("ALT", `${payload.alert || "alert"}: ${parcellaName} — ${tipo}`);
  }

  $statAlerts.textContent = state.activeAlerts.size;
  renderAlerts();
}

// ── Irrigation Commands (UC-03) ──────────────────────────────────────

function sendIrrigationCmd(parcella, azione) {
  if (!client || !state.connected) return;

  const topic = `tenuta/parcella/${parcella}/irrigazione/cmd`;
  const payload = {
    device_id: "dashboard",
    timestamp: new Date().toISOString(),
    type: "comando_irrigazione",
    value: azione,
    unit: "",
    quality: "good",
    metadata: { source: "dashboard", operator: "web" },
  };

  client.publish(topic, JSON.stringify(payload), { qos: 2 });
  state.commandCount++;
  $statCommands.textContent = state.commandCount;

  log("CMD", `${parcella} -> ${azione} (QoS 2)`);
}

// ── Render Alerts ────────────────────────────────────────────────────

function formatDuration(ms) {
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec} sec`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  return `${h}h ${min % 60}m`;
}

function formatTimeShort(ts) {
  return new Date(ts).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
}

function alertValueText(a) {
  const meta = ALERT_VALUE_MAP[a.tipo];
  if (!meta || a.value == null) return a.messaggio || "";
  return `${meta.label}: ${a.value} ${meta.unit} (soglia: ${meta.soglia})`;
}

const LIVELLO_ICON = { critico: "\u{1F534}", alto: "\u{1F7E1}", medio: "\u{1F535}" };
const LIVELLO_LABELS = { gelata: "GELATA", vento: "VENTO FORTE", stress_idrico: "STRESS IDRICO" };

function switchAlertTab(tab) {
  state.alertTab = tab;
  renderAlerts();
}

function renderAlerts() {
  const $container = $("alerts-container");
  if (!$container) return;

  const activeCount = state.activeAlerts.size;
  const historyCount = state.alertHistory.length;

  // Tab header
  const tabsHtml = `
    <div class="alert-tabs">
      <button class="alert-tab ${state.alertTab === "attivi" ? "active" : ""}" onclick="switchAlertTab('attivi')">
        Attivi${activeCount > 0 ? ` (${activeCount})` : ""}
      </button>
      <button class="alert-tab ${state.alertTab === "storico" ? "active" : ""}" onclick="switchAlertTab('storico')">
        Storico${historyCount > 0 ? ` (${historyCount})` : ""}
      </button>
    </div>`;

  if (state.alertTab === "attivi") {
    $container.innerHTML = tabsHtml + renderActiveAlerts();
  } else {
    $container.innerHTML = tabsHtml + renderAlertHistory();
  }
}

function renderActiveAlerts() {
  if (state.activeAlerts.size === 0) {
    return '<div class="alert-empty">Nessun alert attivo — tutto nella norma</div>';
  }

  const now = Date.now();
  let html = "";
  for (const a of state.activeAlerts.values()) {
    const icon = LIVELLO_ICON[a.livello] || "!";
    const tipoLabel = LIVELLO_LABELS[a.tipo] || a.tipo.toUpperCase();
    const duration = formatDuration(now - a.firstSeen);
    const valueText = alertValueText(a);
    html += `
    <div class="alert-item ${a.livello}">
      <div class="alert-icon-emoji">${icon}</div>
      <div class="alert-content">
        <div class="alert-top-row">
          <span class="alert-title-new">${tipoLabel} — ${a.parcellaName}</span>
          <span class="alert-duration">da ${duration}</span>
        </div>
        <div class="alert-detail">${valueText}</div>
        ${a.count > 1 ? `<div class="alert-count">Ricevuto ${a.count} volte</div>` : ""}
      </div>
    </div>`;
  }
  return `<div class="alerts-scroll">${html}</div>`;
}

function renderAlertHistory() {
  if (state.alertHistory.length === 0) {
    return '<div class="alert-empty">Nessun alert nello storico</div>';
  }

  let html = "";
  for (const a of state.alertHistory) {
    const tipoLabel = LIVELLO_LABELS[a.tipo] || a.tipo.toUpperCase();
    const from = formatTimeShort(a.firstSeen);
    const to = formatTimeShort(a.resolvedAt);
    const dur = formatDuration(a.resolvedAt - a.firstSeen);
    html += `
    <div class="alert-history-item ${a.livello}">
      <span class="alert-history-time">${from} – ${to}</span>
      <span class="alert-history-label">${tipoLabel} — ${a.parcellaName}</span>
      <span class="alert-history-dur">durata ${dur}</span>
    </div>`;
  }
  return `<div class="alerts-scroll">${html}</div>`;
}

// Auto-risoluzione: se lastSeen > 30s fa, sposta in history
function checkAlertResolution() {
  const now = Date.now();
  const STALE_THRESHOLD = 30000;

  for (const [key, a] of state.activeAlerts) {
    if (now - a.lastSeen > STALE_THRESHOLD) {
      state.activeAlerts.delete(key);
      state.alertHistory.unshift({ ...a, resolvedAt: now });
      if (state.alertHistory.length > 100) state.alertHistory.pop();
      log("ALT", `Risolto: ${a.parcellaName} — ${a.tipo} (durata ${formatDuration(now - a.firstSeen)})`);
    }
  }

  $statAlerts.textContent = state.activeAlerts.size;
  renderAlerts();
}

setInterval(checkAlertResolution, 15000);

// ── UI Helpers ───────────────────────────────────────────────────────

function updateConnectionUI() {
  if (state.connected) {
    $connectionBadge.classList.add("connected");
    $connectionText.textContent = "Connesso";
  } else {
    $connectionBadge.classList.remove("connected");
    $connectionText.textContent = "Disconnesso";
  }
}

function updateParcellaBadge(parcella) {
  const $badge = $(`badge-${parcella}`);
  if (!$badge) return;

  // Count active sensors for this parcella
  let online = 0;
  let total = 0;
  SENSOR_TYPES.forEach((tipo) => {
    total++;
    const key = `${parcella}/${tipo}`;
    const lastSeen = state.sensorLastSeen[key];
    if (lastSeen && Date.now() - lastSeen < 15000) {
      online++;
    }
  });

  if (online === total) {
    $badge.textContent = "Online";
    $badge.className = "parcella-badge online";
  } else if (online > 0) {
    $badge.textContent = `${online}/${total}`;
    $badge.className = "parcella-badge partial";
  } else {
    $badge.textContent = "Offline";
    $badge.className = "parcella-badge offline";
  }
}

function updateSensorStats() {
  const now = Date.now();
  let online = 0;
  let offline = 0;

  state.activeSensors.forEach((key) => {
    const lastSeen = state.sensorLastSeen[key];
    if (lastSeen && now - lastSeen < 15000) {
      online++;
    } else {
      offline++;
    }
  });

  $statSensors.textContent = online;
  $statOffline.textContent = offline;
}

function formatTime(isoStr) {
  if (!isoStr) return "";
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return "";
  }
}

function log(tag, msg, extra) {
  const time = new Date().toLocaleTimeString("it-IT", {
    hour: "2-digit", minute: "2-digit", second: "2-digit", fractionalSecondDigits: 3,
  });

  const entry = document.createElement("div");
  entry.className = "log-entry";
  entry.innerHTML = `<span class="time">${time}</span> <span class="topic">[${tag}]</span> <span class="msg">${msg}${extra ? " " + extra : ""}</span>`;

  $logPanel.appendChild(entry);

  while ($logPanel.children.length > 200) {
    $logPanel.removeChild($logPanel.firstChild);
  }

  $logPanel.scrollTop = $logPanel.scrollHeight;
}

// Periodically refresh badge statuses and sensor cell staleness
setInterval(() => {
  const now = Date.now();
  PARCELLE.forEach((p) => {
    updateParcellaBadge(p.id);
    SENSOR_TYPES.forEach((tipo) => {
      const cell = $(`cell-${p.id}-${tipo}`);
      if (!cell) return;
      const lastSeen = state.sensorLastSeen[`${p.id}/${tipo}`];
      const age = lastSeen ? now - lastSeen : Infinity;
      cell.classList.toggle("stale-warn", age >= 15000 && age < 3600000);
      cell.classList.toggle("stale-err", age >= 3600000 && age !== Infinity);
    });
  });
  updateSensorStats();
}, 10000);

// Throughput msg/s (media su 2 secondi)
let _lastMsgCount = 0;
setInterval(() => {
  const delta = state.messageCount - _lastMsgCount;
  _lastMsgCount = state.messageCount;
  const rate = (delta / 2).toFixed(0);
  $statMessages.innerHTML = `${rate} <small style="font-size:12px;font-weight:400;">msg/s</small>`;
}, 2000);

// ── Simulator Controls ──────────────────────────────────────────

const SIM_API = "/api/sim";
const SIM_LABELS = {
  microclima: "Microclima",
  suolo: "Suolo",
  elettrovalvola: "Elettrovalvola",
};

// Scenario label shown in the parcelle panel for each simulator
const SIM_SCENARIO_LABELS = {
  microclima: "Gelata",
  suolo: "Stress idrico",
};

// State for accordion and per-parcella config
let simExpandedName = null;
let simParcelleConfig = {};

function renderSimStatus(sims) {
  const $list = $("sim-list");
  if (!$list) return;

  $list.innerHTML = sims.map((s) => {
    const expanded = simExpandedName === s.name;
    const hasPanel = s.name in SIM_SCENARIO_LABELS || s.name === "elettrovalvola";

    return `
    <div class="sim-accordion-header" onclick="simToggleExpand('${s.name}')">
      <div class="sim-accordion-left">
        <span class="sim-dot ${s.running ? "running" : ""}"></span>
        <span class="sim-name">${SIM_LABELS[s.name] || s.name}</span>
        ${hasPanel ? `<span class="sim-accordion-arrow ${expanded ? "expanded" : ""}">&#9654;</span>` : ""}
      </div>
      <div class="sim-actions">
        <button class="btn-sim start" onclick="event.stopPropagation(); simStart('${s.name}')" ${s.running ? "disabled" : ""}>Avvia</button>
        <button class="btn-sim stop" onclick="event.stopPropagation(); simStop('${s.name}')" ${!s.running ? "disabled" : ""}>Ferma</button>
      </div>
    </div>
    <div class="sim-parcelle-panel ${expanded ? "visible" : ""}" id="sim-panel-${s.name}">
      ${expanded ? renderParcellePanel(s.name) : ""}
    </div>`;
  }).join("");
}

function renderParcellePanel(name) {
  if (name === "elettrovalvola") {
    return PARCELLE.map((p) => {
      const v = state.valves[p.id];
      const status = v ? v.status : "chiusa";
      return `
      <div class="sim-parcella-row">
        <span class="sim-parcella-name">${p.nome}</span>
        <span class="sim-parcella-status ${status}">${status}</span>
      </div>`;
    }).join("");
  }

  const scenarioKey = name === "microclima" ? "gelata" : "stress";
  const scenarioLabel = SIM_SCENARIO_LABELS[name];
  const cfg = (simParcelleConfig[name] || {})[scenarioKey] || {};

  return PARCELLE.map((p) => {
    const enabled = !!cfg[p.id];
    return `
    <div class="sim-parcella-row">
      <span class="sim-parcella-name">${p.nome}</span>
      <div class="sim-parcella-right">
        <span class="sim-parcella-label">${scenarioLabel}</span>
        <label class="toggle" onclick="event.stopPropagation()">
          <input type="checkbox" ${enabled ? "checked" : ""}
                 onchange="toggleParcellaConfig('${name}', '${p.id}', this.checked)">
          <span class="toggle-slider"></span>
        </label>
      </div>
    </div>`;
  }).join("");
}

function simToggleExpand(name) {
  simExpandedName = simExpandedName === name ? null : name;
  simFetchStatus();
}

async function toggleParcellaConfig(simulator, parcella, enabled) {
  try {
    await fetch(`${SIM_API}/parcelle-config`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ simulator, parcella, enabled }),
    });
    fetchParcelleConfig();
    const scenarioLabel = SIM_SCENARIO_LABELS[simulator] || simulator;
    const p = PARCELLE.find((x) => x.id === parcella);
    log("SIM", `${p ? p.nome : parcella}: ${scenarioLabel} ${enabled ? "ON" : "OFF"}`);
  } catch { /* ignore */ }
}

async function fetchParcelleConfig() {
  try {
    const resp = await fetch(`${SIM_API}/parcelle-config`);
    if (resp.ok) simParcelleConfig = await resp.json();
  } catch { /* orchestrator not available */ }
}

async function simFetchStatus() {
  try {
    const resp = await fetch(`${SIM_API}/status`);
    if (resp.ok) renderSimStatus(await resp.json());
  } catch { /* orchestrator not available */ }
}

async function simStart(name) {
  await fetch(`${SIM_API}/start/${name}`, { method: "POST" });
  simFetchStatus();
  log("SIM", `Avviato ${SIM_LABELS[name] || name}`);
}

async function simStop(name) {
  await fetch(`${SIM_API}/stop/${name}`, { method: "POST" });
  simFetchStatus();
  log("SIM", `Fermato ${SIM_LABELS[name] || name}`);
}

async function simStartAll() {
  await fetch(`${SIM_API}/start-all`, { method: "POST" });
  simFetchStatus();
  log("SIM", "Avviati tutti i simulatori");
}

async function simStopAll() {
  await fetch(`${SIM_API}/stop-all`, { method: "POST" });
  simFetchStatus();
  log("SIM", "Fermati tutti i simulatori");
}

// Poll simulator status and parcelle config
setInterval(simFetchStatus, 5000);
setInterval(fetchParcelleConfig, 5000);

// ── Load Historical Data from InfluxDB ───────────────────────────

let historyRange = "1h";
// Per custom range: timestamps assoluti in ms
let customFrom = null;
let customTo = null;

async function setTimeRange(range) {
  historyRange = range;
  customFrom = null;
  customTo = null;
  document.querySelectorAll("#time-range-tabs .zone-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.range === range);
  });
  const picker = $("custom-range-picker");
  if (picker) picker.classList.remove("visible");
  await reloadHistory();
}

function toggleCustomRange() {
  const picker = $("custom-range-picker");
  picker.classList.toggle("visible");
  // Pre-fill con range corrente
  if (!$("custom-from").value) {
    const now = new Date();
    const from = new Date(now.getTime() - (RANGE_MS[historyRange] || 3600e3));
    $("custom-from").value = toLocalISOString(from);
    $("custom-to").value = toLocalISOString(now);
  }
}

function toLocalISOString(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function applyCustomRange() {
  const fromVal = $("custom-from").value;
  const toVal = $("custom-to").value;
  if (!fromVal || !toVal) return;
  customFrom = new Date(fromVal).getTime();
  customTo = new Date(toVal).getTime();
  if (customFrom >= customTo) return;
  historyRange = "custom";
  document.querySelectorAll("#time-range-tabs .zone-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.range === "custom");
  });
  await reloadHistory();
  log("SYS", `Custom range: ${fromVal} → ${toVal}`);
}

async function reloadHistory() {
  await loadHistory();
  if (state.selectedParcella) updateCharts(state.selectedParcella);
}

function downsample(points, maxPoints) {
  if (points.length <= maxPoints) return points;
  const step = Math.ceil(points.length / maxPoints);
  const result = [];
  for (let i = 0; i < points.length; i += step) {
    result.push(points[i]);
  }
  // Always include the last point for continuity
  if (result[result.length - 1] !== points[points.length - 1]) {
    result.push(points[points.length - 1]);
  }
  return result;
}

async function loadHistory() {
  let query;
  if (historyRange === "custom" && customFrom && customTo) {
    const fromISO = new Date(customFrom).toISOString();
    const toISO = new Date(customTo).toISOString();
    query = `SELECT value, parcella, tipo FROM microclima WHERE time >= '${fromISO}' AND time <= '${toISO}' ORDER BY time ASC`;
  } else {
    query = `SELECT value, parcella, tipo FROM microclima WHERE time > now() - ${historyRange} ORDER BY time ASC`;
  }

  try {
    const url = `${INFLUXDB_URL}/query?db=${INFLUXDB_BUCKET}&q=${encodeURIComponent(query)}`;
    const resp = await fetch(url, {
      headers: { "Authorization": `Token ${INFLUXDB_TOKEN}` },
    });

    if (!resp.ok) {
      log("ERR", `InfluxDB HTTP ${resp.status}: ${resp.statusText}`);
      return false;
    }

    const json = await resp.json();
    const allSeries = json.results?.[0]?.series;
    if (!allSeries || allSeries.length === 0) {
      log("SYS", `Nessun dato per il range selezionato (${historyRange})`);
      return false;
    }

    // Build new history locally before replacing state
    const newHistory = {};
    PARCELLE.forEach((p) => {
      newHistory[p.id] = {};
      SENSOR_TYPES.forEach((s) => { newHistory[p.id][s] = []; });
    });

    // columns: [time, value, parcella, tipo]
    for (const series of allSeries) {
      if (!series.values) continue;
      for (const row of series.values) {
        const [timeStr, value, parcella, tipo] = row;
        if (!parcella || !tipo || value == null) continue;

        const time = new Date(timeStr).getTime();

        if (newHistory[parcella] && newHistory[parcella][tipo]) {
          newHistory[parcella][tipo].push({ t: time, v: value });
        }

        const key = `${parcella}/${tipo}`;
        if (!state.sensorLastSeen[key] || time > state.sensorLastSeen[key]) {
          state.sensorLastSeen[key] = time;
          state.activeSensors.add(key);
          const $val = $(`val-${parcella}-${tipo}`);
          if ($val) $val.textContent = value;
        }
      }
    }

    // Downsample per range
    const maxPoints = CHART_POINTS_BY_RANGE[historyRange] || 120;
    PARCELLE.forEach((p) => {
      SENSOR_TYPES.forEach((tipo) => {
        newHistory[p.id][tipo] = downsample(newHistory[p.id][tipo], maxPoints);
      });
      updateParcellaBadge(p.id);
    });

    // Success: replace state
    state.history = newHistory;
    updateSensorStats();
    log("SYS", "Dati storici caricati da InfluxDB");
    return true;
  } catch (err) {
    log("ERR", `Caricamento storico fallito: ${err.message}`);
    return false;
  }
}

// ── Boot ─────────────────────────────────────────────────────────────

initUI();
loadHistory();
fetchParcelleConfig();
simFetchStatus();
connect();
