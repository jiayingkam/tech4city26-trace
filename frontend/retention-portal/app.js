// Vanilla JS, no framework, no build step — deliberate for this standalone
// product (see plan). Talks directly to the 5 retention_guard backend
// services over fetch(); CORS on those services is configured to allow this
// page's own origin via FRONTEND_ORIGIN (see shared/trace_cors).

let CONFIG = null;
let policiesCache = [];
let dataSourcesCache = [];

const state = {
  get token() { return localStorage.getItem("rg_token"); },
  set token(v) { v ? localStorage.setItem("rg_token", v) : localStorage.removeItem("rg_token"); },
  get admin() { try { return JSON.parse(localStorage.getItem("rg_admin")); } catch { return null; } },
  set admin(v) { v ? localStorage.setItem("rg_admin", JSON.stringify(v)) : localStorage.removeItem("rg_admin"); },
};

// ── Fetch helper ────────────────────────────────────────────────────────

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function api(baseUrl, path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  const res = await fetch(`${baseUrl}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    logout();
    throw new ApiError(401, "Session expired — please log in again.");
  }
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new ApiError(res.status, (data && data.error) || `Request failed (${res.status})`);
  return data;
}

const businessAdmins = (path, opts) => api(CONFIG.businessAdminsUrl, path, opts);
const dataSources = (path, opts) => api(CONFIG.dataSourcesUrl, path, opts);
const retentionPolicies = (path, opts) => api(CONFIG.retentionPoliciesUrl, path, opts);
const auditLog = (path, opts) => api(CONFIG.auditLogUrl, path, opts);
const enforceRetention = (path, opts) => api(CONFIG.enforceRetentionUrl, path, opts);

// ── Boot ────────────────────────────────────────────────────────────────

async function boot() {
  // Static config.js (not a server route — this page has no backend of its
  // own on Vercel, see config.js's own comment).
  CONFIG = window.RG_CONFIG;
  wireAuthForms();
  wireTabs();
  wireSourceForm();
  wirePolicyForm();
  wireReviewControls();
  wireHistoryControls();
  document.getElementById("logoutBtn").addEventListener("click", logout);

  if (state.token && state.admin) {
    showApp();
  } else {
    showAuth();
  }
}

function showAuth() {
  document.getElementById("authSection").classList.remove("hidden");
  document.getElementById("appSection").classList.add("hidden");
  document.getElementById("whoami").classList.add("hidden");
}

function showApp() {
  document.getElementById("authSection").classList.add("hidden");
  document.getElementById("appSection").classList.remove("hidden");
  const who = document.getElementById("whoami");
  who.classList.remove("hidden");
  document.getElementById("whoamiText").textContent =
    `${state.admin.business_name} (${state.admin.email})`;
  loadDataSources();
  loadPolicies();
}

function logout() {
  state.token = null;
  state.admin = null;
  showAuth();
}

// ── Auth ────────────────────────────────────────────────────────────────

function wireAuthForms() {
  document.querySelectorAll("[data-authtab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-authtab]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const which = btn.dataset.authtab;
      document.getElementById("loginForm").classList.toggle("hidden", which !== "login");
      document.getElementById("signupForm").classList.toggle("hidden", which !== "signup");
    });
  });

  document.getElementById("loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errEl = document.getElementById("loginError");
    errEl.textContent = "";
    const form = new FormData(e.target);
    try {
      const res = await businessAdmins("/login", {
        method: "POST",
        body: { email: form.get("email"), password: form.get("password") },
      });
      state.token = res.token;
      state.admin = res.admin;
      showApp();
    } catch (err) {
      errEl.textContent = err.message;
    }
  });

  document.getElementById("signupForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errEl = document.getElementById("signupError");
    errEl.textContent = "";
    const form = new FormData(e.target);
    try {
      const res = await businessAdmins("/signup", {
        method: "POST",
        body: {
          business_name: form.get("business_name"),
          email: form.get("email"),
          password: form.get("password"),
        },
      });
      state.token = res.token;
      state.admin = res.admin;
      showApp();
    } catch (err) {
      errEl.textContent = err.message;
    }
  });
}

// ── Tabs ────────────────────────────────────────────────────────────────

function wireTabs() {
  document.querySelectorAll("#appSection nav [data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#appSection nav [data-tab]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
      document.getElementById(`tab-${btn.dataset.tab}`).classList.remove("hidden");
      if (btn.dataset.tab === "review") refreshReview();
      if (btn.dataset.tab === "history") refreshHistory();
    });
  });
}

function fmtDate(iso) {
  return iso ? new Date(iso).toLocaleString() : "—";
}

function badge(status) {
  return `<span class="badge badge-${status}">${status}</span>`;
}

// ── Data Sources ────────────────────────────────────────────────────────

function wireSourceForm() {
  document.getElementById("sourceForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errEl = document.getElementById("sourceError");
    errEl.textContent = "";
    const form = new FormData(e.target);
    try {
      await dataSources("/data-sources", {
        method: "POST",
        body: { name: form.get("name"), connection_string: form.get("connection_string") },
      });
      e.target.reset();
      await loadDataSources();
      await loadPolicies(); // policy form's data-source dropdown needs the new source
    } catch (err) {
      errEl.textContent = err.message;
    }
  });
}

async function loadDataSources() {
  dataSourcesCache = await dataSources("/data-sources");
  renderDataSources();
  const select = document.getElementById("policySourceSelect");
  select.innerHTML = dataSourcesCache
    .map((s) => `<option value="${s.data_source_id}">${escapeHtml(s.name)}</option>`)
    .join("");
}

function renderDataSources() {
  const el = document.getElementById("sourcesList");
  if (!dataSourcesCache.length) {
    el.innerHTML = `<p class="empty-note">No data sources registered yet.</p>`;
    return;
  }
  el.innerHTML = dataSourcesCache
    .map(
      (s) => `
    <details class="card source-block" data-source-id="${s.data_source_id}">
      <summary><strong>${escapeHtml(s.name)}</strong> — ${s.db_type} · added ${fmtDate(s.created_at)}
        <button class="btn btn-danger btn-small delete-source-btn" data-id="${s.data_source_id}" style="float:right">Delete</button>
      </summary>
      <div class="columns-body">
        <p class="empty-note">Loading columns…</p>
      </div>
      <form class="inline-form add-column-form">
        <label>Table <input type="text" name="table_name" required placeholder="customers"></label>
        <label>Column <input type="text" name="column_name" required placeholder="email"></label>
        <label>Role
          <select name="column_role">
            <option value="pii">pii</option>
            <option value="subject_id">subject_id</option>
            <option value="activity_timestamp">activity_timestamp</option>
          </select>
        </label>
        <button type="submit" class="btn btn-small">Classify column</button>
      </form>
    </details>`
    )
    .join("");

  el.querySelectorAll(".delete-source-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      if (!confirm("Delete this data source and its column classifications?")) return;
      await dataSources(`/data-sources/${btn.dataset.id}`, { method: "DELETE" });
      await loadDataSources();
    });
  });

  el.querySelectorAll("details.source-block").forEach((details) => {
    const sourceId = details.dataset.sourceId;
    details.addEventListener("toggle", () => {
      if (details.open) loadClassifiedColumns(sourceId, details.querySelector(".columns-body"));
    }, { once: false });
    details.querySelector(".add-column-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = new FormData(e.target);
      await dataSources(`/data-sources/${sourceId}/classified-columns`, {
        method: "POST",
        body: {
          table_name: form.get("table_name"),
          column_name: form.get("column_name"),
          column_role: form.get("column_role"),
        },
      });
      e.target.reset();
      loadClassifiedColumns(sourceId, details.querySelector(".columns-body"));
    });
  });
}

async function loadClassifiedColumns(sourceId, container) {
  const columns = await dataSources(`/data-sources/${sourceId}/classified-columns`);
  if (!columns.length) {
    container.innerHTML = `<p class="empty-note">No columns classified yet.</p>`;
    return;
  }
  container.innerHTML = `
    <table>
      <thead><tr><th>Table</th><th>Column</th><th>Role</th><th></th></tr></thead>
      <tbody>
        ${columns
          .map(
            (c) => `<tr>
              <td>${escapeHtml(c.table_name)}</td>
              <td>${escapeHtml(c.column_name)}</td>
              <td>${escapeHtml(c.column_role)}</td>
              <td><button class="btn btn-small btn-danger delete-column-btn" data-id="${c.classified_column_id}">Remove</button></td>
            </tr>`
          )
          .join("")}
      </tbody>
    </table>`;
  container.querySelectorAll(".delete-column-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      await dataSources(`/classified-columns/${btn.dataset.id}`, { method: "DELETE" });
      loadClassifiedColumns(sourceId, container);
    });
  });
}

// ── Policies ────────────────────────────────────────────────────────────

function wirePolicyForm() {
  document.getElementById("policyForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errEl = document.getElementById("policyError");
    errEl.textContent = "";
    const form = new FormData(e.target);
    const scheduleRaw = form.get("schedule_interval_minutes");
    try {
      await retentionPolicies("/policies", {
        method: "POST",
        body: {
          data_source_id: form.get("data_source_id"),
          table_name: form.get("table_name"),
          inactive_days: Number(form.get("inactive_days")),
          action: form.get("action"),
          schedule_interval_minutes: scheduleRaw ? Number(scheduleRaw) : null,
        },
      });
      e.target.reset();
      await loadPolicies();
    } catch (err) {
      errEl.textContent = err.message;
    }
  });
}

function sourceName(id) {
  const s = dataSourcesCache.find((x) => x.data_source_id === id);
  return s ? s.name : id;
}

async function loadPolicies() {
  policiesCache = await retentionPolicies("/policies");
  renderPolicies();
  const reviewSel = document.getElementById("reviewPolicySelect");
  const historySel = document.getElementById("historyPolicySelect");
  const options = policiesCache
    .map((p) => `<option value="${p.policy_id}">${escapeHtml(p.table_name)} · ${p.inactive_days}d · ${p.action}</option>`)
    .join("");
  reviewSel.innerHTML = options || `<option value="">No policies yet</option>`;
  historySel.innerHTML = `<option value="">All policies</option>` + options;
}

function renderPolicies() {
  const el = document.getElementById("policiesList");
  if (!policiesCache.length) {
    el.innerHTML = `<p class="empty-note">No policies yet.</p>`;
    return;
  }
  el.innerHTML = `
    <table>
      <thead><tr><th>Source</th><th>Table</th><th>Inactive after</th><th>Action</th><th>Schedule</th><th>Enabled</th><th></th></tr></thead>
      <tbody>
        ${policiesCache
          .map(
            (p) => `<tr>
              <td>${escapeHtml(sourceName(p.data_source_id))}</td>
              <td>${escapeHtml(p.table_name)}</td>
              <td>${p.inactive_days} days</td>
              <td>${p.action}</td>
              <td>${p.schedule_interval_minutes ? p.schedule_interval_minutes + " min" : "manual only"}</td>
              <td>
                <button class="btn btn-small toggle-enabled-btn" data-id="${p.policy_id}" data-enabled="${p.enabled}">
                  ${p.enabled ? "Enabled" : "Disabled"}
                </button>
              </td>
              <td><button class="btn btn-small btn-danger delete-policy-btn" data-id="${p.policy_id}">Delete</button></td>
            </tr>`
          )
          .join("")}
      </tbody>
    </table>`;

  el.querySelectorAll(".toggle-enabled-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const nowEnabled = btn.dataset.enabled === "true";
      await retentionPolicies(`/policies/${btn.dataset.id}`, { method: "PATCH", body: { enabled: !nowEnabled } });
      await loadPolicies();
    });
  });
  el.querySelectorAll(".delete-policy-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this policy?")) return;
      await retentionPolicies(`/policies/${btn.dataset.id}`, { method: "DELETE" });
      await loadPolicies();
    });
  });
}

// ── Review & Approve ────────────────────────────────────────────────────

function wireReviewControls() {
  document.getElementById("reviewPolicySelect").addEventListener("change", refreshReview);
  document.getElementById("reviewScanBtn").addEventListener("click", async () => {
    const errEl = document.getElementById("reviewError");
    errEl.textContent = "";
    const policyId = document.getElementById("reviewPolicySelect").value;
    if (!policyId) return;
    try {
      const run = await enforceRetention(`/policies/${policyId}/scan`, { method: "POST" });
      errEl.textContent = `Scan complete: ${run.rows_matched} new match(es) proposed.`;
      errEl.style.color = "var(--ok)";
      await refreshReview();
    } catch (err) {
      errEl.style.color = "var(--danger)";
      errEl.textContent = err.message;
    }
  });
  document.getElementById("reviewApproveBtn").addEventListener("click", async () => {
    const errEl = document.getElementById("reviewError");
    errEl.textContent = "";
    const checked = [...document.querySelectorAll(".proposed-checkbox:checked")].map((c) => c.dataset.id);
    if (!checked.length) return;
    try {
      await Promise.all(checked.map((id) => auditLog(`/actions/${id}`, { method: "PATCH", body: { status: "approved" } })));
      await refreshReview();
    } catch (err) {
      errEl.style.color = "var(--danger)";
      errEl.textContent = err.message;
    }
  });
  document.getElementById("reviewEnforceBtn").addEventListener("click", async () => {
    const errEl = document.getElementById("reviewError");
    errEl.textContent = "";
    const policyId = document.getElementById("reviewPolicySelect").value;
    if (!policyId) return;
    if (!confirm("Enforce all currently-approved actions for this policy? This connects to the live data source and applies the action now.")) return;
    try {
      const run = await enforceRetention(`/policies/${policyId}/enforce`, { method: "POST" });
      errEl.style.color = "var(--ok)";
      errEl.textContent = `Enforced: ${run.rows_matched} row(s) affected.`;
      await refreshReview();
    } catch (err) {
      errEl.style.color = "var(--danger)";
      errEl.textContent = err.message;
    }
  });
}

async function refreshReview() {
  const policyId = document.getElementById("reviewPolicySelect").value;
  const el = document.getElementById("reviewList");
  if (!policyId) {
    el.innerHTML = `<p class="empty-note">Create a policy first.</p>`;
    return;
  }
  const [proposed, approved] = await Promise.all([
    auditLog(`/actions?policy_id=${policyId}&status=proposed`),
    auditLog(`/actions?policy_id=${policyId}&status=approved`),
  ]);

  el.innerHTML = `
    <div class="card">
      <h3>Proposed (${proposed.length})</h3>
      ${proposed.length ? renderActionTable(proposed, true) : `<p class="empty-note">Nothing proposed. Run a scan, or wait for the scheduled sweep.</p>`}
    </div>
    <div class="card">
      <h3>Approved — ready to enforce (${approved.length})</h3>
      ${approved.length ? renderActionTable(approved, false) : `<p class="empty-note">Nothing approved yet.</p>`}
    </div>`;
}

function renderActionTable(actions, withCheckbox) {
  return `<table>
    <thead><tr>${withCheckbox ? "<th></th>" : ""}<th>Subject ID</th><th>Action</th><th>Status</th><th>Proposed</th></tr></thead>
    <tbody>
      ${actions
        .map(
          (a) => `<tr>
            ${withCheckbox ? `<td><input type="checkbox" class="proposed-checkbox" data-id="${a.action_id}"></td>` : ""}
            <td>${escapeHtml(a.subject_id_value)}</td>
            <td>${a.action_type}</td>
            <td>${badge(a.status)}</td>
            <td>${fmtDate(a.created_at)}</td>
          </tr>`
        )
        .join("")}
    </tbody>
  </table>`;
}

// ── History ─────────────────────────────────────────────────────────────

function wireHistoryControls() {
  document.getElementById("historyPolicySelect").addEventListener("change", refreshHistory);
  document.getElementById("historyRefreshBtn").addEventListener("click", refreshHistory);
}

async function refreshHistory() {
  const policyId = document.getElementById("historyPolicySelect").value;
  const qs = policyId ? `?policy_id=${policyId}` : "";
  const runs = await auditLog(`/scan-runs${qs}`);
  const runsEl = document.getElementById("historyScanRuns");
  runsEl.innerHTML = runs.length
    ? `<table>
        <thead><tr><th>Mode</th><th>Status</th><th>Scanned</th><th>Matched</th><th>Started</th><th>Finished</th></tr></thead>
        <tbody>
          ${runs
            .map(
              (r) => `<tr>
                <td>${r.mode}</td>
                <td>${badge(r.status)}</td>
                <td>${r.rows_scanned}</td>
                <td>${r.rows_matched}</td>
                <td>${fmtDate(r.started_at)}</td>
                <td>${fmtDate(r.finished_at)}</td>
              </tr>`
            )
            .join("")}
        </tbody>
      </table>`
    : `<p class="empty-note">No scan runs yet.</p>`;

  const appliedQs = policyId ? `&policy_id=${policyId}` : "";
  const [applied, failed] = await Promise.all([
    auditLog(`/actions?status=applied${appliedQs}`),
    auditLog(`/actions?status=failed${appliedQs}`),
  ]);
  const combined = [...applied, ...failed].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  const actionsEl = document.getElementById("historyActions");
  actionsEl.innerHTML = combined.length
    ? renderActionTable(combined, false)
    : `<p class="empty-note">No applied or failed actions yet.</p>`;
}

// ── Utils ───────────────────────────────────────────────────────────────

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

boot();
