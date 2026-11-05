// Datos simulados para la demo pública (GitHub Pages). Imitan las respuestas reales de la API
// y evolucionan con el tiempo: los workers toman tareas, algunas fallan y se reintentan.

const PROCESSES = ["payment_agreement"];
const ERRORS_TRANSIENT = [
  "TransientError: timeout en el portal: Timeout 15000ms exceeded.",
  "TransientError: Servicio temporalmente no disponible (503)",
];
const ERRORS_BUSINESS = [
  "BusinessRuleError: cliente 1099887766 no existe en el portal",
  "BusinessRuleError: El acuerdo no cubre el 60% mínimo del saldo en mora",
];

function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32);
}

function uuid(rand) {
  const hex = () => Math.floor(rand() * 16).toString(16);
  const part = (n) => Array.from({ length: n }, hex).join("");
  return `${part(8)}-${part(4)}-4${part(3)}-a${part(3)}-${part(12)}`;
}

export function createDemoApi() {
  const rand = rng(20261105);
  const now = () => Date.now();
  const iso = (ms) => new Date(ms).toISOString();
  const bots = [
    { worker_id: "srv-linux-01-w1", hostname: "srv-linux-01", platform: "Linux 6.8.0", alive: true },
    { worker_id: "srv-linux-01-w2", hostname: "srv-linux-01", platform: "Linux 6.8.0", alive: true },
    { worker_id: "srv-win-02-w1", hostname: "srv-win-02", platform: "Windows Server 2022", alive: true },
    { worker_id: "srv-win-03-w1", hostname: "srv-win-03", platform: "Windows Server 2019", alive: false },
  ].map((b) => ({
    ...b,
    processes: PROCESSES,
    state: "IDLE",
    current_task_id: null,
    tasks_ok: 0,
    tasks_failed: 0,
    version: "1.0.0",
    started_at: iso(now() - 6 * 3600e3),
    last_seen_ms: b.alive ? now() : now() - 47 * 60e3,
  }));

  const tasks = [];
  function newTask(createdMs) {
    const doc = String(1000000000 + Math.floor(rand() * 99999999));
    const t = {
      id: uuid(rand),
      process: PROCESSES[0],
      status: "PENDING",
      attempts: 0,
      last_error: null,
      correlation_id: "cartera_mora_30-20261105T080000",
      worker_id: null,
      created_at: iso(createdMs),
      updated_at: iso(createdMs),
      started_at: null,
      finished_at: null,
      duration_seconds: null,
      payload: {
        documento: doc,
        cuotas: 1 + Math.floor(rand() * 12),
        valor_cuota: Math.round(80000 + rand() * 420000),
        fecha_primer_pago: "2026-12-01",
      },
      output: null,
      events: [{ event: "ENQUEUED", attempt: 0, detail: null, worker_id: null, at: iso(createdMs) }],
    };
    tasks.unshift(t);
    return t;
  }

  function finish(t, bot, at) {
    const roll = rand();
    if (t.status !== "RUNNING") t.attempts += 1; // al tomarla ya se contó el intento
    t.worker_id = bot.worker_id;
    t.started_at = iso(at - (20 + rand() * 40) * 1000);
    t.events.push({ event: "STARTED", attempt: t.attempts, detail: null, worker_id: bot.worker_id, at: t.started_at });
    if (roll < 0.82) {
      t.status = "DONE";
      t.finished_at = iso(at);
      t.duration_seconds = (Date.parse(t.finished_at) - Date.parse(t.started_at)) / 1000;
      t.output = { confirmation: `AC-${String(100000 + Math.floor(rand() * 899999))}`, reference: t.id };
      t.last_error = null;
      t.events.push({ event: "COMPLETED", attempt: t.attempts, detail: null, worker_id: null, at: t.finished_at });
      bot.tasks_ok += 1;
    } else if (roll < 0.92 && t.attempts < 4) {
      t.status = "RETRYING";
      t.last_error = ERRORS_TRANSIENT[Math.floor(rand() * ERRORS_TRANSIENT.length)];
      const delay = [10, 60, 300][t.attempts - 1];
      t.events.push({ event: "RETRY_SCHEDULED", attempt: t.attempts, detail: `reintento en ${delay}s: ${t.last_error}`, worker_id: null, at: iso(at) });
    } else {
      t.status = "FAILED";
      t.finished_at = iso(at);
      t.last_error = ERRORS_BUSINESS[Math.floor(rand() * ERRORS_BUSINESS.length)];
      t.events.push({ event: "FAILED", attempt: t.attempts, detail: t.last_error, worker_id: null, at: t.finished_at });
      bot.tasks_failed += 1;
    }
    t.updated_at = iso(at);
  }

  // Historial: ~5 horas de ejecución.
  const alive = bots.filter((b) => b.alive);
  for (let i = 0; i < 160; i++) {
    const at = now() - (5 * 3600e3 * (160 - i)) / 160;
    const t = newTask(at - 120e3);
    finish(t, alive[i % alive.length], at);
    if (t.status === "RETRYING") finish(t, alive[(i + 1) % alive.length], at + 60e3);
  }
  for (let i = 0; i < 6; i++) newTask(now() - (6 - i) * 15000);

  function tick() {
    const t = now();
    for (const bot of alive) {
      bot.last_seen_ms = t - rand() * 8000;
      const current = tasks.find((x) => x.id === bot.current_task_id);
      if (current) {
        finish(current, bot, t);
        bot.current_task_id = null;
        bot.state = "IDLE";
      }
      const next = tasks.find((x) => x.status === "PENDING" || (x.status === "RETRYING" && rand() < 0.3));
      if (next && rand() < 0.8) {
        next.status = "RUNNING";
        next.attempts += 1;
        next.worker_id = bot.worker_id;
        next.updated_at = iso(t);
        bot.current_task_id = next.id;
        bot.state = "BUSY";
      }
    }
    if (rand() < 0.5) newTask(t);
  }
  tick(); // arranca con workers ocupados, como una operación en curso
  setInterval(tick, 5000);

  const clone = (x) => JSON.parse(JSON.stringify(x));
  const publicBot = (b) => {
    const seconds = (now() - b.last_seen_ms) / 1000;
    return {
      worker_id: b.worker_id, hostname: b.hostname, platform: b.platform, processes: b.processes,
      state: b.alive ? b.state : "IDLE", health: seconds <= 60 ? "ONLINE" : "OFFLINE",
      current_task_id: b.current_task_id, tasks_ok: b.tasks_ok, tasks_failed: b.tasks_failed,
      version: b.version, started_at: b.started_at, last_seen: iso(b.last_seen_ms), seconds_since_seen: seconds,
    };
  };

  return {
    async summary() {
      const by_status = { PENDING: 0, RUNNING: 0, RETRYING: 0, DONE: 0, FAILED: 0 };
      tasks.forEach((t) => (by_status[t.status] += 1));
      const hourAgo = now() - 3600e3;
      const recent = (s) => tasks.filter((t) => t.status === s && t.finished_at && Date.parse(t.finished_at) >= hourAgo).length;
      const durations = tasks.filter((t) => t.duration_seconds).map((t) => t.duration_seconds);
      const bs = bots.map(publicBot);
      return {
        by_status,
        by_process: { payment_agreement: by_status },
        success_rate: by_status.DONE / Math.max(1, by_status.DONE + by_status.FAILED),
        done_last_hour: recent("DONE"),
        failed_last_hour: recent("FAILED"),
        avg_duration_seconds: durations.reduce((a, b) => a + b, 0) / Math.max(1, durations.length),
        bots_online: bs.filter((b) => b.health === "ONLINE").length,
        bots_offline: bs.filter((b) => b.health === "OFFLINE").length,
        generated_at: iso(now()),
      };
    },
    async bots() {
      return bots.map(publicBot);
    },
    async tasks(status) {
      const byUpdated = (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at);
      return clone(tasks.filter((t) => !status || t.status === status).sort(byUpdated).slice(0, 100));
    },
    async task(id) {
      const t = tasks.find((x) => x.id === id);
      if (!t) throw new Error("tarea no encontrada");
      return clone(t);
    },
    async requeue(id) {
      const t = tasks.find((x) => x.id === id);
      if (!t || !["FAILED", "PENDING"].includes(t.status)) throw new Error("solo FAILED o PENDING");
      t.status = "PENDING";
      t.finished_at = null;
      t.updated_at = iso(now());
      t.events.push({ event: "REQUEUED", attempt: t.attempts, detail: "reproceso manual", worker_id: null, at: t.updated_at });
      return { task_id: id, status: "PENDING" };
    },
  };
}
