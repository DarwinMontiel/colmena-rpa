// Dashboard del monitor. Sin frameworks: fetch + render. Refresco cada 5 s.
// En GitHub Pages (o con ?demo) usa datos simulados para que la demo funcione sin backend.
import { createDemoApi } from "./demo-data.js";

const REFRESH_MS = 5000;
const params = new URLSearchParams(location.search);
const DEMO = params.has("demo") || location.hostname.endsWith("github.io");

const http = {
  async get(path) {
    const res = await fetch(path, { headers: { Accept: "application/json" } });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  },
  async post(path) {
    const res = await fetch(path, { method: "POST" });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || res.statusText);
    return body;
  },
};

const api = DEMO
  ? createDemoApi()
  : {
      summary: () => http.get("api/summary"),
      bots: () => http.get("api/bots"),
      tasks: (status) => http.get(`api/tasks?limit=100${status ? `&status=${status}` : ""}`),
      task: (id) => http.get(`api/tasks/${id}`),
      requeue: (id) => http.post(`api/tasks/${id}/requeue`),
    };

const state = { status: "" };
const $ = (id) => document.getElementById(id);

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const fmtNum = (n) => (n ?? 0).toLocaleString("es-CO");
const fmtPct = (r) => (r == null ? "–" : `${(r * 100).toFixed(1)} %`);
const fmtSecs = (s) => (s == null ? "–" : s < 60 ? `${s.toFixed(1)} s` : `${(s / 60).toFixed(1)} min`);
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString("es-CO", { dateStyle: "short", timeStyle: "medium" }) : "–");
function fmtAgo(seconds) {
  if (seconds < 60) return `hace ${Math.round(seconds)} s`;
  if (seconds < 3600) return `hace ${Math.round(seconds / 60)} min`;
  return `hace ${Math.round(seconds / 3600)} h`;
}

const fmtCop = (n) =>
  n == null || Number.isNaN(Number(n))
    ? "–"
    : Number(n).toLocaleString("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 });
const fmtDate = (iso) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("es-CO", { day: "numeric", month: "short", year: "numeric" }) : "–";

// La API habla en códigos estables (DONE, BUSY…); el panel los muestra en español.
// El código original queda en el atributo title para soporte técnico.
const STATUS_BADGE = {
  DONE: ["badge-ok", "Completada"],
  FAILED: ["badge-err", "Fallida"],
  RETRYING: ["badge-warn", "Reintentando"],
  RUNNING: ["badge-info", "En ejecución"],
  PENDING: ["badge-muted", "Pendiente"],
  ONLINE: ["badge-ok", "En línea"],
  OFFLINE: ["badge-err", "Sin latido"],
  BUSY: ["badge-info", "Ocupada"],
  IDLE: ["badge-muted", "Libre"],
  STOPPING: ["badge-warn", "Deteniéndose"],
};
const badge = (s) => {
  const [cls, label] = STATUS_BADGE[s] || ["badge-muted", s];
  return `<span class="badge ${cls}" title="${esc(s)}">${esc(label)}</span>`;
};

const EVENT_LABEL = {
  ENQUEUED: "Encolada",
  STARTED: "Tomada por una obrera",
  COMPLETED: "Acuerdo registrado",
  RETRY_SCHEDULED: "Reintento programado",
  FAILED: "Fallida",
  REQUEUED: "Reprocesada",
};
const PROCESS_LABEL = { payment_agreement: "Acuerdos de pago" };
const processName = (p) => PROCESS_LABEL[p] || p;

// Un error de negocio no se reintenta: lo debe revisar cartera, no soporte técnico.
function errorKind(error) {
  if (!error) return "";
  return error.startsWith("BusinessRuleError") || error.startsWith("UnknownProcessError")
    ? `<span class="badge badge-err">Rechazo de negocio · no se reintenta</span>`
    : `<span class="badge badge-warn">Falla técnica · se reintenta con espera</span>`;
}

function agreementSummary(t) {
  const p = t.payload || {};
  if (t.process !== "payment_agreement" || p.cuotas == null) return "";
  const total = Number(p.cuotas) * Number(p.valor_cuota);
  const confirmation = t.output && t.output.confirmation;
  return `<div class="agreement">
      <div class="field"><small>Documento del cliente</small><span class="mono">${esc(p.documento)}</span></div>
      <div class="field"><small>Plan de pago</small>${esc(p.cuotas)} ${Number(p.cuotas) === 1 ? "cuota" : "cuotas"} de ${fmtCop(p.valor_cuota)}</div>
      <div class="field"><small>Total del acuerdo</small><strong>${fmtCop(total)}</strong></div>
      <div class="field"><small>Primer pago</small>${fmtDate(p.fecha_primer_pago)}</div>
      ${confirmation ? `<div class="field"><small>Confirmación del portal</small><span class="mono">${esc(confirmation)}</span></div>` : ""}
    </div>`;
}

function renderSummary(s) {
  const st = s.by_status;
  $("k-done").textContent = fmtNum(st.DONE);
  $("k-done-hour").textContent = `${fmtNum(s.done_last_hour)} en la última hora`;
  $("k-failed").textContent = fmtNum(st.FAILED);
  $("k-failed-hour").textContent = `${fmtNum(s.failed_last_hour)} en la última hora`;
  $("k-running").textContent = fmtNum((st.RUNNING || 0) + (st.RETRYING || 0));
  $("k-pending").textContent = `${fmtNum(st.PENDING)} pendientes en cola`;
  $("k-rate").textContent = fmtPct(s.success_rate);
  $("k-duration").textContent = fmtSecs(s.avg_duration_seconds);
  $("k-bots").textContent = fmtNum(s.bots_online);
  $("k-bots-off").textContent = `${fmtNum(s.bots_offline)} sin latido`;
}

function renderBots(bots) {
  $("bots-body").innerHTML = bots.length
    ? bots
        .map(
          (b) => `<tr>
        <td class="mono">${esc(b.worker_id)}</td>
        <td>${badge(b.health)}</td>
        <td>${badge(b.state)}${b.current_task_id ? ` <span class="mono">${esc(b.current_task_id.slice(0, 8))}</span>` : ""}</td>
        <td>${esc(b.platform)}</td>
        <td>${b.processes.map((p) => esc(processName(p))).join(", ")}</td>
        <td class="num">${fmtNum(b.tasks_ok)}</td>
        <td class="num">${fmtNum(b.tasks_failed)}</td>
        <td title="${esc(fmtTime(b.last_seen))}">${fmtAgo(b.seconds_since_seen)}</td>
      </tr>`,
        )
        .join("")
    : `<tr><td colspan="8" class="empty">Ninguna obrera ha reportado latido todavía</td></tr>`;
}

function renderTasks(tasks) {
  $("tasks-body").innerHTML = tasks.length
    ? tasks
        .map(
          (t) => `<tr class="clickable" data-id="${esc(t.id)}" tabindex="0">
        <td class="mono">${esc(t.id.slice(0, 8))}</td>
        <td>${esc(processName(t.process))}</td>
        <td>${badge(t.status)}</td>
        <td class="num">${t.attempts}</td>
        <td class="mono">${esc(t.worker_id || "–")}</td>
        <td>${fmtTime(t.updated_at)}</td>
        <td class="num">${fmtSecs(t.duration_seconds)}</td>
        <td class="error" title="${esc(t.last_error || "")}">${esc(t.last_error || "")}</td>
      </tr>`,
        )
        .join("")
    : `<tr><td colspan="8" class="empty">No hay tareas para este filtro</td></tr>`;
}

async function openDetail(id) {
  const dialog = $("detail");
  const body = $("detail-body");
  body.innerHTML = "Cargando…";
  dialog.showModal();
  try {
    const t = await api.task(id);
    // La API decide: fallidas siempre; pendientes solo si llevan un tiempo sin movimiento
    // (RPA_REQUEUE_PENDING_AFTER_SECONDS, 15 min por defecto).
    const canRequeue = Boolean(t.can_requeue);
    const requeueHint =
      t.status === "PENDING" && !canRequeue
        ? `<p class="hint">Pendiente reciente: su mensaje sigue en la cola. Se podrá reprocesar cuando lleve un tiempo sin movimiento (15 min por defecto).</p>`
        : "";
    body.innerHTML = `
      ${agreementSummary(t)}
      <div class="grid2">
        <div class="field"><small>Tarea</small><span class="mono">${esc(t.id)}</span></div>
        <div class="field"><small>Estado</small>${badge(t.status)}</div>
        <div class="field"><small>Proceso</small>${esc(processName(t.process))}</div>
        <div class="field"><small>Intentos</small>${t.attempts}</div>
        <div class="field"><small>Lote</small><span class="mono">${esc(t.correlation_id || "–")}</span></div>
        <div class="field"><small>Duración</small>${fmtSecs(t.duration_seconds)}</div>
      </div>
      ${t.last_error ? `<div class="field"><small>Último error</small>${errorKind(t.last_error)}<pre>${esc(t.last_error)}</pre></div>` : ""}
      <details class="field"><summary><small>Datos técnicos (entrada y resultado)</small></summary>
        <pre>${esc(JSON.stringify({ entrada: t.payload, resultado: t.output }, null, 2))}</pre>
      </details>
      <div class="field"><small>Trazabilidad</small>
        <ul class="timeline">${t.events
          .map((e) => `<li><span>${fmtTime(e.at)}</span><span><strong title="${esc(e.event)}">${esc(EVENT_LABEL[e.event] || e.event)}</strong> · intento ${e.attempt}${e.worker_id ? ` · <span class="mono">${esc(e.worker_id)}</span>` : ""}${e.detail ? `<br><span class="hint">${esc(e.detail)}</span>` : ""}</span></li>`)
          .join("")}</ul>
      </div>
      ${requeueHint}
      ${canRequeue ? `<button class="btn" id="requeue">Reprocesar tarea</button>` : ""}`;
    const btn = $("requeue");
    if (btn) {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await api.requeue(id);
          btn.textContent = "Reencolada ✓";
          refresh();
        } catch (err) {
          btn.textContent = `Error: ${err.message}`;
        }
      });
    }
  } catch (err) {
    body.textContent = `No se pudo cargar la tarea: ${err.message}`;
  }
}

async function refresh() {
  try {
    const [summary, bots, tasks] = await Promise.all([api.summary(), api.bots(), api.tasks(state.status)]);
    renderSummary(summary);
    renderBots(bots);
    renderTasks(tasks);
    $("live-dot").className = "dot on";
    $("updated").textContent = `Actualizado ${new Date().toLocaleTimeString("es-CO")}`;
  } catch (err) {
    $("live-dot").className = "dot off";
    $("updated").textContent = `Sin conexión con la API (${err.message})`;
  }
}

$("filters").addEventListener("click", (event) => {
  const chip = event.target.closest(".chip");
  if (!chip) return;
  document.querySelectorAll(".chip").forEach((c) => c.classList.toggle("active", c === chip));
  state.status = chip.dataset.status;
  refresh();
});

$("tasks-body").addEventListener("click", (event) => {
  const row = event.target.closest("tr[data-id]");
  if (row) openDetail(row.dataset.id);
});
$("tasks-body").addEventListener("keydown", (event) => {
  const row = event.target.closest("tr[data-id]");
  if (row && event.key === "Enter") openDetail(row.dataset.id);
});

if (DEMO) {
  $("mode-badge").hidden = false;
  $("api-docs").hidden = true;
}

refresh();
setInterval(refresh, REFRESH_MS);
