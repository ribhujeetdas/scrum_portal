// app/static/js/sprint_viewer.js

(function () {
  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  async function postJson(url, payload) {
    const fetchImpl = window.portalApiFetch || window.fetch.bind(window);
    const resp = await fetchImpl(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify(payload || {}),
    });

    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data || data.ok === false) {
      const err = (data && data.error) ? data.error : `HTTP ${resp.status}`;
      throw new Error(err);
    }
    return data;
  }

  function fmtCountSp(count, sp) {
    const c = (count === null || count === undefined) ? 0 : count;
    const s = (sp === null || sp === undefined) ? 0 : sp;
    return `${c} (${s} SP)`;
  }

  function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function setHtml(id, html) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = html;
  }

  function showError(msg) {
    setText("sv-error", msg || "Something went wrong.");
    const box = document.getElementById("sv-error");
    if (box) box.classList.remove("d-none");
  }

  function clearError() {
    setText("sv-error", "");
    const box = document.getElementById("sv-error");
    if (box) box.classList.add("d-none");
  }

  function clearPanels() {
    setText("sv-summary", "");
    setHtml("sv-groups", "");
    setHtml("sv-metrics", "");
    setHtml("sv-stats", "");
  }

  function renderGroups(groups) {
    // groups already include issue_count and sp_sum from backend
    // Display as: Alice (8 issues, 21 SP)
    let html = "";
    (groups || []).forEach((g) => {
      const name = g.assignee_name || "Unassigned";
      const count = g.issue_count || 0;
      const sp = g.sp_sum || 0;

      html += `
        <div class="sv-group">
          <div class="sv-group-title">${escapeHtml(name)} <span class="sv-group-meta">(${count} issues, ${sp} SP)</span></div>
          <ul class="sv-issue-list">
            ${(g.issues || []).map(renderIssue).join("")}
          </ul>
        </div>
      `;
    });
    return html;
  }

  function renderIssue(it) {
    const key = it.issue_key || "";
    const summary = it.summary || "";
    const sp = (it.story_points === null || it.story_points === undefined || it.story_points === "") ? "-" : it.story_points;
    const status = it.status || "";
    const type = it.issue_type || "";
    const app = it.app_name || "";
    const feature = it.feature_key || "";

    return `
      <li class="sv-issue">
        <a class="sv-issue-key" href="#" data-issue-key="${escapeAttr(key)}" data-issue-url="${escapeAttr(it.issue_key || "")}">
          ${escapeHtml(key)}
        </a>
        <span class="sv-scope-star" data-issue-key="${escapeAttr(key)}"></span>
        <span class="sv-issue-summary">${escapeHtml(summary)}</span>
        <span class="sv-pill">${escapeHtml(type)}</span>
        <span class="sv-pill">${escapeHtml(status)}</span>
        <span class="sv-pill">SP: ${escapeHtml(String(sp))}</span>
        ${app ? `<span class="sv-pill">App: ${escapeHtml(app)}</span>` : ""}
        ${feature ? `<span class="sv-pill">Epic: ${escapeHtml(feature)}</span>` : ""}
      </li>
    `;
  }

  function renderStats(stats) {
    if (!stats) return "";
    return `
      <div class="sv-stats-grid">
        <div class="sv-stat">Unestimated: <b>${stats.unestimated_count}</b> (${stats.unestimated_pct}%)</div>
        <div class="sv-stat">Bugs: <b>${stats.bug_count}</b> (${stats.bug_pct}%)</div>
        <div class="sv-stat">Bug SP: <b>${stats.bug_sp}</b></div>
        <div class="sv-stat">Unassigned: <b>${stats.unassigned_count}</b> (${stats.unassigned_pct}%)</div>
        <div class="sv-stat">0 Comments: <b>${stats.zero_comment_count}</b> (${stats.zero_comment_pct}%)</div>
      </div>
    `;
  }

  function renderMetrics(m) {
    if (!m) return "";

    // Single-sprint metrics only
    const rows = [
      ["Committed", fmtCountSp(m.committed_count, m.committed_sp)],
      ["Delivered", fmtCountSp(m.delivered_count, m.delivered_sp)],
      ["Spillover", fmtCountSp(m.spillover_count, m.spillover_sp)],
      ["Scope Added", fmtCountSp(m.scope_added_count, m.scope_added_sp)],
      ["Descope", fmtCountSp(m.descope_count, m.descope_sp)],

      ["Predictability", `${m.predictability_pct}%`],
      ["Completion (SP)", `${m.completion_sp_pct}%`],
      ["Completion (Count)", `${m.completion_count_pct}%`],
      ["Unplanned Work (SP)", `${m.unplanned_sp_pct}%`],
      ["Unplanned Work (Count)", `${m.unplanned_count_pct}%`],
      ["Scope Churn (SP)", `${m.scope_churn_sp_pct}%`],
      ["Scope Churn (Count)", `${m.scope_churn_count_pct}%`],
      ["Spill % (of Total SP)", `${m.spill_pct}%`],
      ["Scope Added % (of Committed SP)", `${m.scope_pct}%`],
    ];

    const html = rows.map(([k, v]) => `
      <div class="sv-metric-row">
        <div class="sv-metric-k">${escapeHtml(k)}</div>
        <div class="sv-metric-v">${escapeHtml(String(v))}</div>
      </div>
    `).join("");

    return `<div class="sv-metrics-grid">${html}</div>
      <div class="sv-legend"><b>*</b> indicates an issue <b>added after sprint start</b>.</div>
    `;
  }

  function applyScopeStars(scopeAddedKeys) {
    const set = new Set(scopeAddedKeys || []);
    document.querySelectorAll(".sv-scope-star").forEach((el) => {
      const key = el.getAttribute("data-issue-key");
      if (set.has(key)) {
        el.innerHTML = "<b>*</b>";
        el.title = "Added after sprint start";
      } else {
        el.innerHTML = "";
      }
    });
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;"
    }[c]));
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/"/g, "&quot;");
  }

  async function loadSprints(projectKey, boardId, refresh) {
    const data = await postJson("/automation/sprint-viewer/sprints", {
      project_key: projectKey,
      board_id: boardId,
      refresh: !!refresh
    });

    const sel = document.getElementById("sv-sprint");
    if (!sel) return;

    sel.innerHTML = `<option value="">Select sprint</option>`;
    (data.sprints || []).forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = `${s.name} (${s.state})`;
      sel.appendChild(opt);
    });
  }

  async function loadSprintDetails(boardId, sprintId) {
    clearError();
    clearPanels();

    // 1) Fetch issues first (fast)
    const issuesData = await postJson("/automation/sprint-viewer/issues", {
      board_id: boardId,
      sprint_id: sprintId
    });

    setText("sv-summary", `Total: ${issuesData.total} (${issuesData.total_sp} SP)`);
    setHtml("sv-groups", renderGroups(issuesData.groups));
    setHtml("sv-stats", renderStats(issuesData.stats));

    // 2) Fetch metrics after (async)
    const metricsData = await postJson("/automation/sprint-viewer/metrics", {
      board_id: boardId,
      sprint_id: sprintId,
      total_sp: issuesData.total_sp,
      total_count: issuesData.total
    });

    setHtml("sv-metrics", renderMetrics(metricsData.metrics));
    applyScopeStars(metricsData.metrics.scope_added_keys || []);
  }

  function wireUp() {
    const projectSel = document.getElementById("sv-project");
    const boardSel = document.getElementById("sv-board");
    const sprintSel = document.getElementById("sv-sprint");
    const refreshBtn = document.getElementById("sv-refresh-sprints");

    if (!projectSel || !boardSel || !sprintSel) return;

    projectSel.addEventListener("change", () => {
      const pk = projectSel.value;
      const boardsJson = boardSel.getAttribute("data-boards-by-project");
      const boardsByProject = boardsJson ? JSON.parse(boardsJson) : {};
      boardSel.innerHTML = `<option value="">Select board</option>`;

      (boardsByProject[pk] || []).forEach((b) => {
        const opt = document.createElement("option");
        opt.value = b.board_id;
        opt.textContent = `${b.board_name} (${b.board_type || ""})`;
        boardSel.appendChild(opt);
      });

      sprintSel.innerHTML = `<option value="">Select sprint</option>`;
      clearPanels();
    });

    boardSel.addEventListener("change", async () => {
      clearError();
      clearPanels();
      const pk = projectSel.value;
      const bid = boardSel.value;
      sprintSel.innerHTML = `<option value="">Loading...</option>`;
      if (!pk || !bid) return;

      try {
        await loadSprints(pk, bid, false);
      } catch (e) {
        showError(e.message);
        sprintSel.innerHTML = `<option value="">Select sprint</option>`;
      }
    });

    if (refreshBtn) {
      refreshBtn.addEventListener("click", async () => {
        clearError();
        clearPanels();
        const pk = projectSel.value;
        const bid = boardSel.value;
        if (!pk || !bid) return;

        sprintSel.innerHTML = `<option value="">Refreshing...</option>`;
        try {
          await loadSprints(pk, bid, true);
        } catch (e) {
          showError(e.message);
          sprintSel.innerHTML = `<option value="">Select sprint</option>`;
        }
      });
    }

    sprintSel.addEventListener("change", async () => {
      clearError();
      clearPanels();
      const bid = boardSel.value;
      const sid = sprintSel.value;
      if (!bid || !sid) return;

      try {
        await loadSprintDetails(bid, sid);
      } catch (e) {
        showError(e.message);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", wireUp);
})();
