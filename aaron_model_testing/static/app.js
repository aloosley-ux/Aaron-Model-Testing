"use strict";
const $ = (s, root = document) => root.querySelector(s);
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const num = (v, digits = 1) =>
  v == null
    ? "—"
    : Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });
const pct = (v) => (v == null ? "—" : `${num(v * 100)}%`);
const date = (v) => (v ? new Date(v).toLocaleString() : "—");
const billions = v => typeof v === 'number' ? num(v / 1e9, 2) : '—';
const colors = [
  "#087e7c",
  "#719736",
  "#bf7649",
  "#568abe",
  "#9371b0",
  "#b85c77",
];
const state = {
  models: [],
  profiles: [],
  runs: [],
  selected: new Set(),
  board: [],
  group: "all",
  polling: false,
};
async function api(path, method = "GET", body) {
  const r = await fetch("/api" + path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(
      typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail),
    );
  }
  return r.json();
}
function toast(message) {
  $("#toast").textContent = message;
  $("#toast").style.display = "block";
  setTimeout(() => ($("#toast").style.display = "none"), 7000);
}
function badge(status) {
  return `<span class="badge ${["completed", "ready"].includes(status) ? "good" : ["failed", "cancelled", "interrupted"].includes(status) ? "bad" : ["partial", "running"].includes(status) ? "warn" : ""}">${esc(status)}</span>`;
}
function head(title, subtitle, actions = "") {
  return `<div class="page-head"><div><h1>${esc(title)}</h1><p class="muted">${esc(subtitle)}</p></div><div class="actions">${actions}</div></div>`;
}
function empty(title, body, action = "") {
  return `<div class="empty"><div class="empty-symbol">◈</div><h2>${esc(title)}</h2><p>${esc(body)}</p>${action}</div>`;
}
function table(headers, rows) {
  return `<div class="table-wrap"><table><thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}
function median(row, key) {
  return row.summary?.metrics?.[key]?.median;
}
function card(label, value, note) {
  return `<div class="card"><div class="card-label">${esc(label)}</div><div class="card-value">${value}</div><div class="card-note">${esc(note)}</div></div>`;
}
function bars(values, unit = "", max = null) {
  const ceiling = max || Math.max(...values.map((v) => v.value || 0), 1);
  return values
    .map(
      (v, i) =>
        `<div class="bar-row"><span title="${esc(v.label)}">${esc(v.label)}</span><span class="bar-track"><i style="width:${Math.max(0, Math.min(100, ((v.value || 0) / ceiling) * 100))}%;background:${v.color || colors[i % colors.length]}"></i></span><span>${num(v.value)}${unit}</span></div>`,
    )
    .join("");
}
function scatter(rows) {
  if (!rows.length)
    return empty(
      "Your comparison starts here",
      "Run a full benchmark to plot capability against generation speed. Each point represents a measured model profile.",
    );
  const width = 650,
    height = 245,
    left = 54,
    right = 20,
    top = 20,
    bottom = 40,
    maxX =
      Math.max(...rows.map((r) => median(r, "generation_tps") || 0), 1) * 1.15;
  let svg = `<svg class="chart" role="img" aria-label="Generation speed versus capability" viewBox="0 0 ${width} ${height}">`;
  for (let i = 0; i <= 4; i++) {
    const y = top + ((height - top - bottom) * i) / 4;
    svg += `<line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" stroke="#e6edef"/><text x="${left - 10}" y="${y + 4}" text-anchor="end">${100 - i * 25}%</text>`;
  }
  for (let i = 0; i <= 4; i++) {
    const x = left + ((width - left - right) * i) / 4;
    svg += `<text x="${x}" y="${height - 19}" text-anchor="middle">${num((maxX * i) / 4, 0)}</text>`;
  }
  svg += `<text x="${width / 2}" y="${height - 2}" text-anchor="middle">Generation tok/s →</text>`;
  rows.forEach((r, i) => {
    const x =
        left +
        ((median(r, "generation_tps") || 0) / maxX) * (width - left - right),
      y = top + (1 - (r.summary.capability || 0)) * (height - top - bottom);
    svg += `<a href="#run/${esc(r.run_id)}"><circle cx="${x}" cy="${y}" r="7" fill="${colors[i % colors.length]}" stroke="white" stroke-width="2"><title>${esc(r.model_name)} · ${esc(r.profile_name)}: ${num(median(r, "generation_tps"))} tok/s, ${pct(r.summary.capability)} capability</title></circle></a>`;
  });
  return (
    svg +
    "</svg>" +
    `<div class="legend">${rows
      .slice(0, 6)
      .map(
        (r, i) =>
          `<span><i style="background:${colors[i % colors.length]}"></i>${esc(r.model_name)} / ${esc(r.profile_name)}</span>`,
      )
      .join("")}</div>`
  );
}
function curves(runs, key, label) {
  const points = runs
    .flatMap((r, i) =>
      Object.entries(r.summary?.contexts || {}).map(([c, m]) => ({
        x: Number(c),
        y: m[key]?.median,
        color: colors[i % colors.length],
        label: r.profile?.name || r.profile_name || r.id.slice(0, 6),
      })),
    )
    .filter((p) => p.y != null);
  if (!points.length)
    return empty(
      "No context measurements yet",
      "Performance runs will add measured context curves here.",
    );
  const xs = [...new Set(points.map((p) => p.x))].sort((a, b) => a - b),
    maxY = Math.max(...points.map((p) => p.y), 1) * 1.1,
    w = 650,
    h = 245,
    l = 55,
    t = 20,
    b = 40;
  const x = (n) =>
      l +
      (xs.length > 1 ? xs.indexOf(n) / (xs.length - 1) : 0.5) * (w - l - 25),
    y = (n) => t + (1 - n / maxY) * (h - t - b);
  let s = `<svg class="chart" role="img" aria-label="${esc(label)} by context" viewBox="0 0 ${w} ${h}">`;
  for (let i = 0; i <= 4; i++) {
    const yy = y((maxY * i) / 4);
    s += `<line x1="${l}" x2="${w - 25}" y1="${yy}" y2="${yy}" stroke="#e5edef"/><text x="${l - 8}" y="${yy + 4}" text-anchor="end">${num((maxY * i) / 4, 0)}</text>`;
  }
  runs.forEach((r, i) => {
    const pp = points
      .filter((p) => p.color === colors[i % colors.length])
      .sort((a, b) => a.x - b.x);
    s += `<polyline fill="none" stroke="${colors[i % colors.length]}" stroke-width="2" points="${pp.map((p) => `${x(p.x)},${y(p.y)}`).join(" ")}"/>`;
    pp.forEach(
      (p) =>
        (s += `<circle cx="${x(p.x)}" cy="${y(p.y)}" r="5" fill="${p.color}"><title>${esc(p.label)}: ${p.x} ctx, ${num(p.y)} ${esc(label)}</title></circle>`),
    );
  });
  xs.forEach(
    (n) =>
      (s += `<text x="${x(n)}" y="${h - 19}" text-anchor="middle">${num(n, 0)}</text>`),
  );
  s += `<text x="${w / 2}" y="${h - 2}" text-anchor="middle">Configured context tokens</text></svg>`;
  return (
    s +
    `<div class="legend">${runs.map((r, i) => `<span><i style="background:${colors[i % colors.length]}"></i>${esc(r.profile?.name || r.profile_name || r.id.slice(0, 6))}</span>`).join("")}</div>`
  );
}
async function loadCore() {
  [state.models, state.profiles, state.runs] = await Promise.all([
    api("/models"),
    api("/profiles"),
    api("/runs"),
  ]);
}
async function leaderboard() {
  await loadCore();
  state.board = await api("/leaderboard");
  const groups = [...new Set(state.board.map((r) => r.comparability_group))];
  const rows =
    state.group === "all"
      ? state.board
      : state.board.filter((r) => r.comparability_group === state.group);
  const plotted = rows.filter(
    (r) => r.summary.capability != null && median(r, "generation_tps") != null,
  );
  const bestGen = Math.max(
      ...rows.map((r) => median(r, "generation_tps") || 0),
      0,
    ),
    bestCap = Math.max(...rows.map((r) => r.summary.capability || 0), 0);
  $("#content").innerHTML =
    head(
      "The local model leaderboard",
      "Find the right model for the job. Compare measured tradeoffs across saved profiles.",
      `<button data-action="scan">Scan models</button>`,
    ) +
    `<div class="cards">${card("MODELS IN INVENTORY", num(state.models.filter((m) => m.status === "ready").length, 0), "GGUFs registered on this machine")}${card("FASTEST GENERATION", bestGen ? `${num(bestGen)} <small>tok/s</small>` : "—", "Median across successful repeated samples")}${card("HIGHEST CAPABILITY", bestCap ? pct(bestCap) : "—", "Agent core v1 · deterministic checks")}${card("MEASURED PROFILES", num(state.board.length, 0), "Smoke runs excluded from leaderboard")}</div>` +
    `<div class="grid-two"><div class="panel"><div class="panel-title"><div><h2>Capability × speed</h2><p>Explore the tradeoff. Click a point to inspect its run.</p></div><span class="badge dark">NO COMPOSITE SCORE</span></div>${scatter(plotted)}</div><div class="panel"><h2>Generation throughput</h2><p class="muted small">Decode rate from llama.cpp native timings</p>${rows.length ? bars(rows.slice(0, 7).map((r) => ({ label: r.model_name, value: median(r, "generation_tps") }))) : empty("No measured profiles", "Register a GGUF, save a profile and run your first benchmark.")}</div></div>` +
    `<div class="panel"><div class="panel-title"><div><h2>Measured model profiles</h2><p>Latest result for each configuration and controlled workload</p></div><div class="actions"><select class="pill-select" id="group-select"><option value="all">All workload groups</option>${groups.map((g, i) => `<option value="${g}" ${state.group === g ? "selected" : ""}>Workload ${i + 1} · ${g.slice(0, 8)}</option>`).join("")}</select><button data-action="compare">Compare selected (${state.selected.size})</button></div></div>${
      rows.length
        ? table(
            [
              "Select",
              "Model / profile",
              "Generation",
              "Prompt",
              "TTFT",
              "Capability",
              "RAM peak",
              "Reliability",
              "Result",
            ],
            rows.map(
              (r) =>
                `<tr><td><input type="checkbox" aria-label="Compare ${esc(r.model_name)}" data-select="${r.run_id}" ${state.selected.has(r.run_id) ? "checked" : ""}></td><td><a href="#model/${r.model_id}"><strong>${esc(r.model_name)}</strong></a><small>${esc(r.quantisation)} · ${esc(r.profile_name)} · workload ${r.comparability_group.slice(0, 8)}</small></td><td class="numeric">${num(median(r, "generation_tps"))}<small>tok/s</small></td><td class="numeric">${num(median(r, "prompt_tps"), 0)}<small>tok/s</small></td><td>${num(median(r, "ttft_ms"), 0)} ms</td><td>${pct(r.summary.capability)}<small>${r.summary.capability_samples || 0} samples</small></td><td>${num(r.ram_peak_mb, 0)} MB<small>VRAM ${num(r.vram_peak_mb, 0)} MB</small></td><td>${pct(r.summary.reliability)}</td><td><a href="#run/${r.run_id}">${badge(r.status)} ↗</a></td></tr>`,
            ),
          )
        : empty(
            "Ready for your first measurement",
            "No fabricated results are shown. Start with a pipeline smoke test, then optimise a profile and run the full suite.",
            `<button class="primary" data-action="run">New benchmark</button>`,
          )
    }</div>` +
    `<div class="notice">Hardware and workloads stay controlled; each model can use its own supported runtime settings. Compare matching workload groups. RAM is process RSS. Driver VRAM and busiest-engine utilisation are sampled on Windows when available.</div>`;
}
async function models() {
  await loadCore();
  const scan = (await api("/jobs")).find(j=>j.kind==='scan' && j.result);
  $("#content").innerHTML =
    head(
      "Model inventory",
      "Register local GGUFs from as many directories as you need.",
      `<button class="primary" data-action="scan">+ Scan files or directories</button>`,
    ) +
    `<div class="panel">${
      state.models.length
        ? table(
            [
              "Model",
              "Architecture / quant",
              "Size",
              "Parameters",
              "Context",
              "Profiles",
              "Status",
            ],
            state.models.map((m) => {
              const pp = state.profiles.filter((p) => p.model_id === m.id),
                best = pp.find((p) => p.optimisation_run_id);
              return `<tr><td><a href="#model/${m.id}"><strong>${esc(m.name)}</strong></a><small title="${esc(m.path)}">${esc(m.filename)}</small></td><td>${esc(m.architecture)}<small>${esc(m.quantisation)}</small></td><td>${num(m.size_bytes / 2 ** 30, 2)} GB</td><td>${num(m.parameter_count / 1e9, 2)} B</td><td>${num(m.context_capability, 0)}</td><td>${pp.length}${best ? `<small>Best tested: ${esc(best.name)}</small>` : ""}</td><td>${badge(m.status)}</td></tr>`;
            }),
          )
        : empty(
            "Add the models you already have",
            "Scan a directory or register a single .gguf file. Header metadata and all model bytes are fingerprinted; files remain in their original locations.",
            `<button class="primary" data-action="scan">Scan model directory</button>`,
          )
    }</div>` + (scan ? `<div class="panel"><h2>Last inventory scan</h2><p class="small muted">${esc(date(scan.finished_at))} · ${scan.result.registered.length} registered · ${scan.result.failures.length} unreadable</p>${scan.result.failures.length ? `<pre>${esc(JSON.stringify(scan.result.failures,null,2))}</pre>` : '<span class="badge good">All discovered files registered</span>'}</div>` : '');
}
async function modelDetail(id) {
  const m = await api("/models/" + id);
  const latest = m.runs.find(
    (r) =>
      r.stage === "full" &&
      !r.smoke &&
      ["completed", "partial"].includes(r.status),
  );
  $("#content").innerHTML =
    head(
      m.name,
      `${m.architecture} · ${m.quantisation} · ${num(m.size_bytes / 2 ** 30, 2)} GB`,
      `<button data-action="profile" data-id="${id}">+ Save profile</button><button class="primary" data-action="run" data-id="${id}">Benchmark / optimise</button>`,
    ) +
    `<div class="cards">${card("PARAMETERS", `${num(m.parameter_count / 1e9, 2)} <small>B</small>`, "From tensor dimensions")}${card("DECLARED CONTEXT", num(m.context_capability, 0), "GGUF capability; tested separately")}${card("SAVED PROFILES", num(m.profiles.length, 0), "Immutable settings revisions")}${card("HISTORICAL RUNS", num(m.runs.length, 0), "All attempts remain inspectable")}</div>` +
    `${
      latest
        ? `<div class="grid-two"><div class="panel"><h2>Latest measured performance</h2>${curves([latest], "generation_tps", "Generation tok/s")}</div><div class="panel"><h2>Latest capability categories</h2>${bars(
            Object.entries(latest.summary.categories || {}).map(([k, v]) => ({
              label: k.replaceAll("_", " "),
              value: v.score * 100,
            })),
            "%",
            100,
          )}</div></div>`
        : ""
    }<div class="grid-two"><div class="panel"><h2>Model metadata</h2><p class="small muted">${esc(m.path)}</p><pre>${esc(JSON.stringify({ sha256: m.sha256, hash_kind: m.hash_kind, source: m.source || "Unknown", notes: m.notes, embedded_chat_template: !!m.chat_template, external_template: m.external_template_path, files: m.files }, null, 2))}</pre><button data-action="model-notes" data-id="${id}">Edit name / source / notes</button><details><summary>All GGUF metadata</summary><pre>${esc(JSON.stringify(m.metadata, null, 2))}</pre></details><details><summary>Embedded chat template</summary><pre>${esc(m.chat_template || "No embedded template. Set an external Jinja template in a saved profile.")}</pre></details></div>
    <div class="panel"><h2>Saved configurations</h2><p class="muted small">FAST, BALANCED and SMART describe intentions. Intelligence is measured by the suite.</p>${m.profiles.map((p) => `<div class="profile-card"><h3>${esc(p.name)} ${p.optimisation_run_id ? '<span class="badge good">OPTIMISED</span>' : ""}</h3><p class="small muted">${date(p.created_at)} · ${p.config_sha256.slice(0, 10)}</p><p class="small">Context ${num(p.config.ctx_size, 0)} · GPU layers ${p.config.gpu_layers} · FA ${p.config.flash_attn ? "on" : "off"} · KV ${esc(p.config.cache_type_k)}/${esc(p.config.cache_type_v)}</p><p class="small muted">${esc(p.notes || "")}</p><div class="actions"><button data-action="command" data-id="${p.id}">Exact launch command</button><button data-action="profile-copy" data-id="${p.id}" data-model="${id}">Copy / edit</button></div></div>`).join("") || empty("Save your first profile", "Start with a supported Vulkan baseline, then run quick optimisation.", `<button data-action="profile" data-id="${id}">Save profile</button>`)}</div></div>` +
    `<div class="panel"><h2>Run history</h2>${runTable(m.runs)}</div>`;
}
function runTable(rows) {
  return rows.length
    ? table(
        [
          "Compare",
          "Created",
          "Model / profile",
          "Stage",
          "Samples",
          "Speed",
          "Reliability",
          "Status",
        ],
        rows.map(
          (r) =>
            `<tr><td><input type="checkbox" data-select="${r.id}" aria-label="Select run ${r.id}" ${state.selected.has(r.id) ? "checked" : ""}></td><td><a href="#run/${r.id}">${esc(date(r.created_at))}</a><small class="mono">${r.id.slice(0, 10)}</small></td><td>${esc(state.models.find((m) => m.id === r.model_id)?.name || r.model_id)}<small>${esc(r.profile?.name)}</small></td><td>${esc(r.stage)} ${r.smoke ? '<span class="badge warn">SMOKE</span>' : ""}</td><td>${r.sample_count}</td><td>${num(median(r, "generation_tps"))} tok/s</td><td>${pct(r.summary?.reliability)}</td><td>${badge(r.status)}</td></tr>`,
        ),
      )
    : empty(
        "No runs yet",
        "Every benchmark and optimisation attempt will be recorded here.",
      );
}
async function runs() {
  await loadCore();
  $("#content").innerHTML =
    head(
      "Run history",
      "Inspect every measurement, candidate, response and failure.",
      `<button data-action="compare">Compare selected (${state.selected.size})</button>`,
    ) + `<div class="panel">${runTable(state.runs)}</div>`;
}
async function runDetail(id) {
  const r = await api("/runs/" + id),
    s = r.summary || {},
    records = r.records || [],
    caps = records.filter((t) => t.type === "capability"),
    candidates = records.filter((t) => t.type === "candidate");
  const metrics = s.metrics || {};
  $("#content").innerHTML =
    head(
      r.model.name,
      `${r.profile.name} · ${r.stage} · ${date(r.created_at)}`,
      `<span>${badge(r.status)}</span><a class="primary" style="padding:9px 14px;border-radius:8px" href="/api/runs/${id}/artifacts">Download artifacts</a>`,
    ) +
    (r.smoke
      ? '<div class="notice warning">Pipeline smoke test. These measurements validate the workflow and are excluded from the leaderboard.</div>'
      : "") +
    (r.error ? `<div class="notice warning">${esc(r.error)}</div>` : "") +
    `<div class="cards">${card("GENERATION", `${num(metrics.generation_tps?.median)} <small>tok/s</small>`, "Native decode rate · successful samples")}${card("PROMPT PROCESSING", `${num(metrics.prompt_tps?.median, 0)} <small>tok/s</small>`, "Prompt cache disabled")}${card("CAPABILITY", pct(s.capability), `${s.capability_samples || 0} graded samples`)}${card("RELIABILITY", pct(s.reliability), `${s.errors || 0} inference failures`)}</div>` +
    `<div class="grid-two"><div class="panel"><h2>Generation across contexts</h2>${curves([r], "generation_tps", "Generation tok/s")}</div><div class="panel"><h2>Capability by category</h2>${
      Object.keys(s.categories || {}).length
        ? bars(
            Object.entries(s.categories).map(([k, v]) => ({
              label: k.replaceAll("_", " "),
              value: v.score * 100,
              color: colors[0],
            })),
            "%",
            100,
          )
        : empty(
            "No scored capability results",
            "Optimisation uses unscored workloads; run capability qualification next.",
          )
    }</div></div>` +
    `<div class="panel"><h2>Measurement distribution</h2><p class="small muted">Individual runs are preserved. Variance uses the sample (n−1) denominator; a single sample has no variance.</p>${table(
      ["Metric", "N", "Median", "Minimum", "Maximum", "Variance"],
      Object.entries(metrics).map(
        ([k, v]) =>
          `<tr><td>${esc(k)}</td><td>${v.n}</td><td>${num(v.median)}</td><td>${num(v.min)}</td><td>${num(v.max)}</td><td>${num(v.variance, 3)}</td></tr>`,
      ),
    )}</div>` +
    (r.winner
      ? `<div class="panel"><h2>Winning configuration</h2><p>Saved ${esc(r.request.profile_name)} profile <span class="mono">${r.winner.profile_id}</span></p><pre>${esc(JSON.stringify(r.winner.config, null, 2))}</pre></div>`
      : "") +
    (candidates.length
      ? `<div class="panel"><h2>Every optimisation candidate</h2>${table(
          [
            "Candidate",
            "GPU",
            "Threads",
            "Batch / ubatch",
            "FA / mmap",
            "KV",
            "Objective",
            "Outcome",
          ],
          candidates.map(
            (c) =>
              `<tr class="test-result" data-action="inspect" data-run="${id}" data-id="${c.id}"><td>${c.candidate}</td><td>${c.config.gpu_layers}</td><td>${c.config.threads}</td><td>${c.config.batch_size}/${c.config.ubatch_size}</td><td>${c.config.flash_attn ? "on" : "off"} / ${c.config.mmap ? "on" : "off"}</td><td>${c.config.cache_type_k}/${c.config.cache_type_v}</td><td>${num(c.objective, 3)}</td><td>${c.stable ? badge("ready") : `<span class="badge bad" title="${esc(c.error)}">failed</span>`}</td></tr>`,
          ),
        )}</div>`
      : "") +
    `<div class="panel"><h2>Response inspector</h2><p class="small muted">Click a row to see the exact prompt, rule, raw answer, reasoning, timings and settings.</p>${
      caps.length
        ? table(
            ["Test", "Category", "Context", "Repeat", "Score", "Result"],
            caps.map(
              (t) =>
                `<tr class="test-result" tabindex="0" data-action="inspect" data-run="${id}" data-id="${t.id}"><td>${esc(t.test_id)}</td><td>${esc(t.category)}</td><td>${t.context_size}</td><td>${t.repeat + 1}</td><td>${pct(t.grade.score)}</td><td>${t.grade.passed ? '<span class="badge good">pass</span>' : `<span class="badge bad" title="${esc(t.grade.detail)}">fail</span>`}</td></tr>`,
            ),
          )
        : empty(
            "No capability responses",
            "Performance and tuning samples are available below.",
          )
    }
    <details><summary>Individual performance, lifecycle and error records</summary>${table(
      ["Sample", "Type", "Context", "Result"],
      records
        .filter((t) => t.type !== "capability" && t.type !== "candidate")
        .map(
          (t) =>
            `<tr class="test-result" data-action="inspect" data-run="${id}" data-id="${t.id}"><td>${esc(t.id)}</td><td>${esc(t.type)}</td><td>${t.context_size || "—"}</td><td>${esc(t.error || (t.metrics ? num(t.metrics.generation_tps) + " tok/s" : "Lifecycle / telemetry"))}</td></tr>`,
        ),
    )}</details></div>` +
    `<div class="panel"><h2>Reproduce this run</h2><p class="small muted">Benchmark ${esc(r.benchmark.id)} · machine ${esc(r.environment?.fingerprint?.slice(0, 12))} · group ${esc(r.comparability_group?.slice(0, 12))}</p>${(r.commands || []).map((c) => `<details><summary>${esc(c.workspace)} — exact command and profile</summary><pre class="command">${esc(c.command)}</pre><pre>${esc(JSON.stringify(c.config, null, 2))}</pre></details>`).join("")}<details><summary>Full manifest</summary><pre>${esc(JSON.stringify({ ...r, records: undefined, runtime: r.runtime ? { ...r.runtime, help: "See runtime.json in artifact archive" } : undefined }, null, 2))}</pre></details></div>`;
}
async function compare() {
  await loadCore();
  const selected = state.runs.filter((r) => state.selected.has(r.id));
  if (selected.length < 2) {
    $("#content").innerHTML =
      head(
        "Compare profiles",
        "Select two to six recorded runs to compare their measured tradeoffs.",
      ) +
      `<div class="panel">${runTable(state.runs)}<button data-action="compare">Compare selected (${state.selected.size})</button></div>`;
    return;
  }
  const result = await api(
    "/compare?ids=" +
      selected
        .map((r) => r.id)
        .slice(0, 6)
        .join(","),
  );
  const rr = result.runs;
  $("#content").innerHTML =
    head(
      "Profile comparison",
      "Separate speed, capability and reliability. No single combined ranking.",
      `<button data-action="clear-selection">Clear selection</button>`,
    ) +
    (result.warning
      ? `<div class="notice warning">${esc(result.warning)}</div>`
      : `<div class="notice">Matching machine, runtime build, benchmark version and controlled workload.</div>`) +
    `<div class="cards">${rr.map((r, i) => card(`${state.models.find((m) => m.id === r.model_id)?.name || r.model_id} / ${r.profile.name}`, `<span style="color:${colors[i % colors.length]}">${num(median(r, "generation_tps"))} <small>tok/s</small></span>`, `${pct(r.summary.capability)} capability · ${pct(r.summary.reliability)} reliability`)).join("")}</div>` +
    `<div class="grid-two"><div class="panel"><h2>Generation tok/s</h2>${curves(rr, "generation_tps", "Generation tok/s")}</div><div class="panel"><h2>Prompt tok/s</h2>${curves(rr, "prompt_tps", "Prompt tok/s")}</div></div><div class="grid-two"><div class="panel"><h2>Time to first generated token (ms)</h2>${curves(rr, "ttft_ms", "TTFT ms")}</div><div class="panel"><h2>Capability categories</h2>${[
      ...new Set(rr.flatMap((r) => Object.keys(r.summary.categories || {}))),
    ]
      .map(
        (k) =>
          `<h3 class="small">${esc(k.replaceAll("_", " "))}</h3>${bars(
            rr.map((r, i) => ({
              label: r.profile.name,
              value:
                r.summary.categories?.[k]?.score == null
                  ? null
                  : r.summary.categories[k].score * 100,
              color: colors[i % colors.length],
            })),
            "%",
            100,
          )}`,
      )
      .join("")}</div></div>` +
    `<div class="panel"><h2>History links and settings</h2>${runTable(rr)}${table(
      [
        "Profile",
        "RAM peak MB",
        "VRAM sampled peak MB",
        "CPU mean %",
        "GPU busiest engine %",
        "Load median ms",
      ],
      rr.map(
        (r) =>
          `<tr><td>${esc(r.profile.name)}</td>${["ram_peak_mb", "vram_peak_mb", "cpu_mean_percent", "gpu_utilisation_percent"].map((k) => `<td>${num(r.summary.resources?.[k]?.max)}</td>`).join("")}<td>${num(r.summary.metrics?.load_ms?.median, 0)}</td></tr>`,
      ),
    )}<p class="small muted">RAM, allocation logs, load timing, individual samples and exact settings are available in each run. Driver counter sampling may be unavailable or sparse for short runs.</p></div>`;
}
async function tests() {
  const { suite, lock } = await api("/tests");
  $("#content").innerHTML =
    head(
      "Benchmark definitions",
      `${suite.id} · version ${suite.version} · immutable, hash checked`,
    ) +
    `<div class="notice">${esc(suite.description)} Scored questions are never used for runtime optimisation. Strict output tasks reject extra prose; raw reasoning is preserved separately.</div><div class="panel">${suite.tests.map((t) => `<details><summary><strong>${esc(t.id)}</strong> · ${esc(t.category)} ${t.smoke ? '<span class="badge">SMOKE SUBSET</span>' : ""}</summary><h3>Prompt</h3><pre>${esc(t.prompt)}</pre><h3>Deterministic scoring rule</h3><pre>${esc(JSON.stringify(t.rule, null, 2))}</pre></details>`).join("")}</div><div class="panel"><h2>Long-context matrix</h2><p>Exact retrieval; retrieval plus reasoning; combining distant facts; retaining an earlier instruction; rejecting conflicting distractors.</p><p class="muted small">Default insertion depths: 10%, 50%, 90%. Input length and actual insertion depths are measured with the model tokenizer. Generation space is reserved. Failed context loads count as failed scheduled samples.</p><pre>${esc(JSON.stringify(lock, null, 2))}</pre></div>`;
}
async function settings() {
  const s = await api("/settings");
  $("#content").innerHTML =
    head(
      "Runtime settings",
      "Use your existing native Vulkan build. Settings are saved locally.",
    ) +
    `<div class="panel"><form id="settings-form"><label class="field">llama-server.exe path<input name="server_binary" value="${esc(s.server_binary)}" required></label><label class="field">llama-bench.exe path (optional, for manual cross-checks)<input name="bench_binary" value="${esc(s.bench_binary)}"></label><label class="field">Model directories — one per line<textarea name="model_directories">${esc(s.model_directories.join("\n"))}</textarea></label><div class="form-grid"><label class="field">Vulkan device<input name="device" value="${esc(s.device)}" required></label><label class="field">Benchmark port<input value="1235 (dedicated)" disabled></label><label class="field">Load timeout (seconds)<input name="startup_timeout" type="number" min="10" max="900" value="${s.startup_timeout}"></label><label class="field">Request timeout (seconds)<input name="request_timeout" type="number" min="5" max="1800" value="${s.request_timeout}"></label></div><label class="checkbox"><input name="gpu_telemetry" type="checkbox" ${s.gpu_telemetry ? "checked" : ""}> Sample Windows GPU process counters (adds periodic query overhead)</label><div class="actions"><button class="primary">Save settings</button><button type="button" data-action="runtime">Inspect runtime / hardware</button></div></form></div><div class="notice">The benchmark process binds 127.0.0.1:1235 with one lane. No code attaches to or stops Cortana's port 1234. Ctrl+C closes owned processes; nothing runs as a permanent service.</div>`;
}
function modal(title, html) {
  $("#modal-title").textContent = title;
  $("#modal-body").innerHTML = html;
  $("#modal").showModal();
}
async function scanModal() {
  const s = await api("/settings");
  modal(
    "Scan local GGUF files",
    `<form id="scan-form"><p class="muted small">Add directories or individual .gguf files, one per line. SHA256 reads every model byte and may take several minutes. All split shards are fingerprinted.</p><label class="field">Paths<textarea name="roots" required>${esc(s.model_directories.join("\n"))}</textarea></label><div class="dialog-footer"><button class="primary">Start inventory scan</button></div></form>`,
  );
}
async function profileModal(modelId, copyId) {
  await loadCore();
  const original = state.profiles.find((p) => p.id === copyId);
  const c = original?.config || {
    gpu_layers: 999,
    threads: 7,
    batch_threads: 7,
    batch_size: 512,
    ubatch_size: 128,
    flash_attn: true,
    mmap: true,
    ctx_size: 4096,
    cache_type_k: "f16",
    cache_type_v: "f16",
    options: {},
    template: null,
    sampling: {
      temperature: 0,
      top_p: 1,
      top_k: 0,
      min_p: 0,
      repeat_penalty: 1,
      seed: 42,
      enable_thinking: false,
      token_budget: 1024,
    },
  };
  modal(
    "Save model profile",
    `<form id="profile-form" data-model="${modelId}"><p class="small muted">A saved revision preserves all settings and template contents. Use model-specific sampling and reasoning settings where supported.</p><label class="field">Profile name<input name="name" value="${esc(original?.name || "BALANCED")}" required maxlength="60"></label><label class="field">Runtime / sampling configuration (JSON)<textarea name="config" style="min-height:380px" required>${esc(JSON.stringify(c, null, 2))}</textarea></label><label class="field">Notes<input name="notes" value="${esc(original?.notes || "")}"></label><p class="small muted">GPU layers 999 requests full offload; try partial offload for larger models. Context stays fixed unless you request an optional context sweep. Runtime options use a validated allowlist.</p><div class="dialog-footer"><button class="primary">Save profile revision</button></div></form>`,
  );
}
async function runModal(modelId) {
  await loadCore();
  const ready = state.models.filter((m) => m.status === "ready");
  if (!ready.length) {
    await scanModal();
    return;
  }
  const chosen = modelId || ready[0].id;
  const profiles = state.profiles.filter((p) => p.model_id === chosen);
  modal(
    "New benchmark",
    `<form id="run-form"><div class="form-grid"><label class="field">Model<select name="model_id" id="run-model">${ready.map((m) => `<option value="${m.id}" ${m.id === chosen ? "selected" : ""}>${esc(m.name)}</option>`).join("")}</select></label><label class="field">Saved profile<select name="profile_id" id="run-profile" required>${profiles.map((p) => `<option value="${p.id}">${esc(p.name)} · ${p.config_sha256.slice(0, 7)}</option>`).join("")}</select></label></div><button type="button" class="link-button" data-action="profile" data-id="${chosen}">+ Create a profile</button><div class="hr"></div><div class="form-grid"><label class="field">Stage<select name="stage" id="run-stage"><option value="full">Performance + capability</option><option value="optimise">Automatic optimisation</option><option value="performance">Performance only</option><option value="capability">Capability only</option></select></label><label class="field">Repeats<input name="repeats" type="number" min="3" max="10" value="3" required></label></div><label class="checkbox"><input name="smoke" type="checkbox"> Pipeline smoke test (small subset; excluded from leaderboard)</label><div class="form-grid"><label class="field">Context sizes, comma separated<input name="contexts" value="2048,4096,8192" required></label><label class="field">Performance generation tokens<input name="generation_tokens" type="number" value="128" min="16" max="1024"></label></div><label class="checkbox"><input name="long_context" type="checkbox" checked> Include long-context capability matrix (can take substantial time)</label><details><summary>Optimisation depth and profile objective</summary><div class="form-grid"><label class="field">Search preset<select name="preset"><option>quick</option><option>standard</option><option>thorough</option><option>drill</option></select></label><label class="field">Save winner as<select name="profile_name"><option>BALANCED</option><option>FAST</option><option>SMART</option></select></label><label class="field">Optional tuning contexts (comma separated)<input name="tune_contexts" placeholder="Blank = selected profile context"></label><label class="field">Load observations per context<input name="load_repeats" type="number" value="3" min="1" max="5"></label><label class="field">Candidate budget (blank = preset default)<input name="candidate_limit" type="number" min="1" max="128"></label></div><p class="small muted">Quick 8 → standard 24 → thorough 64 → drill 32 around your selected profile. Every candidate repeats at least three times. SMART uses your profile's chosen context and reasoning settings; its intelligence is assessed separately.</p></details><div class="dialog-footer"><button class="primary" ${profiles.length ? "" : "disabled"}>Queue benchmark</button></div></form>`,
  );
}
async function inspector(runId, sampleId) {
  const r = await api(`/runs/${runId}/responses/${sampleId}`);
  if (r.type !== "capability") {
    modal("Sample " + r.id, `<pre>${esc(JSON.stringify(r, null, 2))}</pre>`);
    return;
  }
  modal(
    r.test_id,
    `<p>${r.grade.passed ? '<span class="badge good">PASS</span>' : '<span class="badge bad">FAIL</span>'} ${pct(r.grade.score)} · ${esc(r.category)} · context ${r.context_size} · repeat ${r.repeat + 1}</p><div class="notice ${r.grade.passed ? "" : "warning"}">${esc(r.grade.detail)} ${esc(r.error || "")}</div><h3>Exact prompt</h3><pre>${esc(JSON.stringify(r.test?.messages || r.request?.messages, null, 2))}</pre><h3>Expected result / scoring rule</h3><pre>${esc(JSON.stringify(r.test?.rule, null, 2))}</pre><h3>Raw model answer</h3><pre>${esc(r.response || "(No final answer)")}</pre><h3>Native tool calls</h3><pre>${esc(JSON.stringify(r.tool_calls || [], null, 2))}</pre><details><summary>Raw reasoning</summary><pre>${esc(r.reasoning || "(None returned)")}</pre></details><details><summary>Timing, grade and exact runtime configuration</summary><pre>${esc(JSON.stringify({ metrics: r.metrics, finish_reason: r.finish_reason, grade: r.grade, runtime_config: r.runtime_config, test_sha256: r.test_sha256, prompt_sha256: r.prompt_sha256, insertion_positions: r.test?.insertion_positions }, null, 2))}</pre></details><details><summary>Full request and stream</summary><pre>${esc(JSON.stringify({ request: r.request, events: r.events }, null, 2))}</pre></details>`,
  );
}
async function render() {
  const [view, id] = (location.hash.slice(1) || "leaderboard").split("/");
  document
    .querySelectorAll("nav a")
    .forEach((a) =>
      a.classList.toggle(
        "active",
        a.dataset.view === view ||
          (view === "model" && a.dataset.view === "models") ||
          (view === "run" && a.dataset.view === "runs"),
      ),
    );
  try {
    if (view === "model") await modelDetail(id);
    else if (view === "run") await runDetail(id);
    else
      await (
        { leaderboard, models, runs, compare, tests, settings }[view] ||
        leaderboard
      )();
  } catch (e) {
    $("#content").innerHTML =
      head("Unable to load this view", e.message) +
      `<button data-action="refresh">Retry</button>`;
    toast(e.message);
  }
}
document.addEventListener("click", async (event) => {
  const el = event.target.closest("[data-action]");
  if (!el) return;
  try {
    const id = el.dataset.id;
    switch (el.dataset.action) {
      case "scan":
        await scanModal();
        break;
      case "run":
        await runModal(id);
        break;
      case "profile":
        $("#modal").close();
        await profileModal(id);
        break;
      case "profile-copy":
        await profileModal(el.dataset.model, id);
        break;
      case "inspect":
        await inspector(el.dataset.run, id);
        break;
      case "command": {
        const r = await api(`/profiles/${id}/command`);
        modal(
          "Exact native launch command",
          `<pre class="command">${esc(r.command)}</pre><pre>${esc(JSON.stringify(r.argv, null, 2))}</pre><p class="small muted">Preview only. Benchmark launches are owned and supervised by the app.</p>`,
        );
        break;
      }
      case "model-notes": {
        const m = await api("/models/" + id);
        modal(
          "Model notes",
          `<form id="notes-form" data-model="${id}"><label class="field">Name<input name="name" value="${esc(m.name)}" required></label><label class="field">Source repository / URL<input name="source" value="${esc(m.source || "")}"></label><label class="field">Notes<textarea name="notes">${esc(m.notes)}</textarea></label><button class="primary">Save</button></form>`,
        );
        break;
      }
      case "runtime":
        toast("Inspecting native binary and Windows hardware…");
        modal(
          "Runtime and hardware",
          `<pre>${esc(JSON.stringify(await api("/runtime"), null, 2))}</pre>`,
        );
        break;
      case "compare":
        if (state.selected.size < 2) {
          toast("Select at least two recorded runs");
          location.hash = "compare";
        } else {
          location.hash = "compare";
          await render();
        }
        break;
      case "clear-selection":
        state.selected.clear();
        await render();
        break;
      case "cancel":
        await api(`/jobs/${id}/cancel`, "POST");
        toast("Cancellation requested; owned processes are shutting down");
        await poll();
        break;
      case "refresh":
        await render();
        break;
    }
  } catch (e) {
    toast(e.message);
  }
});
document.addEventListener("change", (event) => {
  const el = event.target;
  if (el.dataset.select) {
    el.checked
      ? state.selected.add(el.dataset.select)
      : state.selected.delete(el.dataset.select);
    document
      .querySelectorAll('[data-action="compare"]')
      .forEach(
        (b) => (b.textContent = `Compare selected (${state.selected.size})`),
      );
  }
  if (el.id === "group-select") {
    state.group = el.value;
    render();
  }
  if (el.id === "run-model") {
    const pp = state.profiles.filter((p) => p.model_id === el.value);
    $("#run-profile").innerHTML = pp
      .map(
        (p) =>
          `<option value="${p.id}">${esc(p.name)} · ${p.config_sha256.slice(0, 7)}</option>`,
      )
      .join("");
    $('#run-form button[type="button"]').dataset.id = el.value;
    $("#run-form .primary").disabled = !pp.length;
  }
});
document.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target,
    data = Object.fromEntries(new FormData(form)),
    button = $("button.primary", form);
  if (button) button.disabled = true;
  try {
    switch (form.id) {
      case "scan-form": {
        await api("/models/scan", "POST", {
          roots: data.roots
            .split("\n")
            .map((s) => s.trim())
            .filter(Boolean),
        });
        $("#modal").close();
        toast("Inventory scan queued");
        break;
      }
      case "profile-form": {
        await api(`/models/${form.dataset.model}/profiles`, "POST", {
          name: data.name,
          config: JSON.parse(data.config),
          notes: data.notes,
        });
        $("#modal").close();
        location.hash = "model/" + form.dataset.model;
        await render();
        toast("Profile revision saved");
        break;
      }
      case "run-form": {
        const body = {
          ...data,
          repeats: Number(data.repeats),
          contexts: data.contexts.split(",").map(Number),
          generation_tokens: Number(data.generation_tokens),
          smoke: !!data.smoke,
          long_context: !!data.long_context,
        };
        body.candidate_limit = data.candidate_limit
          ? Number(data.candidate_limit)
          : null;
        body.load_repeats = Number(data.load_repeats);
        body.tune_contexts = data.tune_contexts
          ? data.tune_contexts.split(",").map(Number)
          : null;
        await api("/runs", "POST", body);
        $("#modal").close();
        location.hash = "runs";
        await render();
        toast("Benchmark queued");
        break;
      }
      case "settings-form": {
        await api("/settings", "PUT", {
          ...data,
          model_directories: data.model_directories
            .split("\n")
            .map((s) => s.trim())
            .filter(Boolean),
          startup_timeout: Number(data.startup_timeout),
          request_timeout: Number(data.request_timeout),
          benchmark_port: 1235,
          gpu_telemetry: !!data.gpu_telemetry,
        });
        toast("Settings saved");
        break;
      }
      case "notes-form": {
        await api("/models/" + form.dataset.model, "PATCH", data);
        $("#modal").close();
        await render();
        break;
      }
    }
    await poll();
  } catch (e) {
    toast(e.message);
  } finally {
    if (button) button.disabled = false;
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.matches(".test-result")) e.target.click();
});
$("#new-run").addEventListener("click", () =>
  runModal().catch((e) => toast(e.message)),
);
$("#close-modal").addEventListener("click", () => $("#modal").close());
let previousActive = false;
async function poll() {
  if (state.polling) return;
  state.polling = true;
  try {
    const jobs = await api("/jobs"),
      active = jobs.filter((j) => ["queued", "running"].includes(j.status));
    $("#job-strip").innerHTML = active
      .map(
        (j) =>
          `<div><span><span class="progress ${j.status === "running" ? "running" : ""}">${esc(j.status)}</span> ${esc(j.progress)} ${j.run_id ? `<a href="#run/${j.run_id}">Inspect run ↗</a>` : ""}</span><button class="danger" data-action="cancel" data-id="${j.id}">Cancel</button></div>`,
      )
      .join("");
    if (previousActive && !active.length) {
      await render();
      const last = jobs[0];
      if (last?.error) toast(last.error);
    }
    previousActive = !!active.length;
  } catch (e) {
    $("#job-strip").innerHTML =
      "<span>Connection lost. Start the app to reconnect.</span>";
  } finally {
    state.polling = false;
  }
}
window.addEventListener("hashchange", render);
render();
poll();
setInterval(poll, 3000);
