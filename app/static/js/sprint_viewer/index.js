import { getJson, pollDelay, postJson } from "./api.js";
import { beginAction, createSprintState, disposeAction, isCurrent } from "./state.js";
import {
  renderCore,
  renderMetrics,
  resetResults,
  setMetricsPending,
  showMessage,
  showProgress,
} from "./render.js";
import { downloadWorkbook } from "./export.js";

let disposeCurrent = null;

function option(value, label) {
  const element = document.createElement("option"); element.value = value; element.textContent = label; return element;
}

function errorText(error, fallback) {
  return error?.payload?.error?.message || error?.message || fallback;
}

function groupIssues(issues) {
  const groups = new Map();
  issues.forEach((issue) => {
    const key = issue.principal_id || issue.assignee_eid || "UNASSIGNED";
    if (!groups.has(key)) groups.set(key, { principal_id: key, assignee_eid: issue.assignee_eid, assignee_name: issue.assignee_name, issues: [], issue_count: 0, sp_sum: 0 });
    const group = groups.get(key); group.issues.push(issue); group.issue_count += 1;
    const points = Number(issue.story_points); if (Number.isFinite(points)) group.sp_sum += points;
  });
  return Array.from(groups.values()).map((group) => ({ ...group, sp_sum: Number(group.sp_sum.toFixed(2)) })).sort((a, b) => String(a.assignee_name || "").localeCompare(String(b.assignee_name || "")));
}

export function initSprintViewer(page, apiFetch) {
  if (page.dataset.sprintViewerInitialized === "true") return disposeCurrent || (() => {});
  page.dataset.sprintViewerInitialized = "true";
  const state = createSprintState();
  const boards = JSON.parse(page.getAttribute("data-boards") || "{}");
  const jiraBaseUrl = page.getAttribute("data-jira-base-url") || "";
  const project = document.getElementById("projectKey");
  const board = document.getElementById("boardId");
  const sprint = document.getElementById("sprintId");
  const refresh = document.getElementById("refreshSprintsBtn");
  const fetchButton = document.getElementById("fetchIssuesBtn");
  const download = document.getElementById("downloadSprintReportBtn");
  const retryMetrics = document.getElementById("retryMetricsBtn");
  const expanded = new Set();
  let unchangedPolls = 0;
  let lastFingerprint = "";

  function updateControls() {
    board.disabled = !project.value;
    sprint.disabled = !board.value;
    refresh.disabled = !board.value;
    fetchButton.disabled = !(board.value && sprint.value);
  }

  function populateBoards() {
    board.replaceChildren(option("", "-- Select Board --"));
    (boards[project.value] || []).forEach((item) => board.appendChild(option(item.board_id, item.board_name)));
    sprint.replaceChildren(option("", "-- Select Sprint --"));
    updateControls();
  }

  async function loadSprints(force) {
    const generation = state.actionGeneration;
    sprint.disabled = true; refresh.disabled = true;
    showProgress(force ? "Refreshing sprints…" : "Loading sprints…");
    try {
      const { payload } = await postJson(apiFetch, "/api/automation/sprint-viewer/sprints", {
        project_key: project.value, board_id: Number(board.value), refresh: Boolean(force),
      }, state.controller?.signal);
      if (!isCurrent(state, generation)) return;
      sprint.replaceChildren(option("", "-- Select Sprint --"));
      (payload.sprints || []).forEach((item) => sprint.appendChild(option(item.id, item.name)));
      showProgress(payload.sprints?.length ? "" : "No matching closed sprints");
    } catch (error) {
      if (error.name !== "AbortError") showMessage("danger", errorText(error, "Unable to load sprints."));
      showProgress("");
    } finally {
      if (isCurrent(state, generation)) updateControls();
    }
  }

  async function fetchAllCore(status, generation) {
    const revision = status.components?.core?.revision;
    if (!revision || state.fetchedCoreRevision === revision) return;
    let cursor = null; let first = null;
    do {
      const query = new URLSearchParams({ view_id: state.viewId, revision: String(revision), limit: "500" });
      if (cursor) query.set("cursor", cursor);
      const { payload } = await getJson(apiFetch, `/api/automation/sprint-viewer/snapshots/${state.snapshotId}/issues?${query}`, state.controller.signal);
      if (!isCurrent(state, generation)) return;
      if (!first) first = payload;
      (payload.groups || []).forEach((group) => (group.issues || []).forEach((issue) => state.issues.set(String(issue.issue_id || issue.issue_key), issue)));
      cursor = payload.next_cursor || null;
      showProgress(cursor ? `Loading ticket page… ${state.issues.size} tickets ready` : "Calculating metrics…");
    } while (cursor);
    state.fetchedCoreRevision = revision;
    const data = { ...first, groups: groupIssues(Array.from(state.issues.values())) };
    state.core = data;
    renderCore(data, jiraBaseUrl, expanded, new Set(state.metrics?.scope_added_keys || []));
    setMetricsPending();
    showMessage("success", "Tickets loaded. Metrics and enrichment are continuing in the background.");
    fetchButton.disabled = false;
    fetchButton.textContent = "Start Over";
  }

  async function fetchComponent(key, revision, generation) {
    if (!revision || state.fetchedComponents.get(key) === revision) return;
    const query = new URLSearchParams({ view_id: state.viewId, revision: String(revision) });
    const { payload } = await getJson(apiFetch, `/api/automation/sprint-viewer/snapshots/${state.snapshotId}/components/${key}?${query}`, state.controller.signal);
    if (!isCurrent(state, generation) || !payload.ok) return;
    state.fetchedComponents.set(key, revision);
    if (key === "metrics") {
      state.metrics = payload.data;
      renderMetrics(state.metrics);
      if (state.core) renderCore({ ...state.core, groups: groupIssues(Array.from(state.issues.values())) }, jiraBaseUrl, expanded, new Set(state.metrics.scope_added_keys || []));
    } else if (key === "history") {
      Object.entries(payload.data?.issues || {}).forEach(([id, historical]) => {
        const existing = state.issues.get(id); if (existing) state.issues.set(id, { ...existing, ...historical });
      });
      if (state.core) renderCore({ ...state.core, groups: groupIssues(Array.from(state.issues.values())) }, jiraBaseUrl, expanded, new Set(state.metrics?.scope_added_keys || []));
    } else if (key === "comments") {
      Object.entries(payload.data?.issues || {}).forEach(([id, comments]) => {
        const existing = state.issues.get(id); if (existing) state.issues.set(id, { ...existing, comment_total: comments.comment_total, relevant_comment_count: comments.relevant_comment_count });
      });
      if (state.core && payload.data?.stats) state.core = { ...state.core, stats: payload.data.stats };
      if (state.core) renderCore({ ...state.core, groups: groupIssues(Array.from(state.issues.values())) }, jiraBaseUrl, expanded, new Set(state.metrics?.scope_added_keys || []));
    }
  }

  async function applyStatus(status, generation) {
    state.snapshotId = status.snapshot_id; state.viewId = status.view_id;
    state.serverGeneration = status.generation; state.responseRevision = status.response_revision;
    state.components = status.components || {}; state.access = status.access || {};
    if (state.components.core?.state === "ready" && state.access.core === "granted") await fetchAllCore(status, generation);
    for (const key of ["history", "comments", "metrics"]) {
      if (state.components[key]?.state === "ready" && state.access[key === "metrics" ? "metrics" : key] === "granted") {
        await fetchComponent(key, state.components[key].revision, generation);
      }
    }
    const metricFailed = ["metrics", "original_commitment", "completed_original", "total_completed", "added_scope", "removed_scope"].find((key) => state.components[key]?.state === "failed");
    retryMetrics?.classList.toggle("d-none", !metricFailed);
    download.disabled = !(status.export_ready && state.metrics && state.issues.size);
    if (state.core && !state.metrics) showProgress(metricFailed ? "Metrics could not be loaded. Retry is available." : "Calculating metrics…");
    if (state.metrics) showProgress("");
  }

  async function poll(generation, initialStatus = null) {
    if (initialStatus) await applyStatus(initialStatus, generation);
    if (!isCurrent(state, generation)) return;
    const query = new URLSearchParams({ view_id: state.viewId });
    try {
      const { payload, retryAfter } = await getJson(apiFetch, `/api/automation/sprint-viewer/snapshots/${state.snapshotId}/status?${query}`, state.controller.signal);
      if (!isCurrent(state, generation)) return;
      const fingerprint = JSON.stringify([payload.response_revision, payload.access, payload.components]);
      unchangedPolls = fingerprint === lastFingerprint ? unchangedPolls + 1 : 0; lastFingerprint = fingerprint;
      await applyStatus(payload, generation);
      const terminalAccess = ["granted", "denied", "unavailable"].includes(payload.access?.core);
      const terminalData = payload.state === "ready" || payload.state === "failed";
      if (!(terminalData && terminalAccess && state.metrics)) {
        state.timer = window.setTimeout(() => poll(generation), pollDelay(unchangedPolls, retryAfter));
      }
    } catch (error) {
      if (!isCurrent(state, generation) || error.name === "AbortError") return;
      if (error.status === 401 || error.status === 403) {
        disposeAction(state); resetResults(); showMessage("danger", "Your Jira or portal access is no longer valid. Sign in and try again."); return;
      }
      showProgress("Connection interrupted. Retrying report status…");
      state.timer = window.setTimeout(() => poll(generation), pollDelay(unchangedPolls + 1));
    }
  }

  async function startReport() {
    const selection = {
      projectKey: project.value, boardId: Number(board.value), boardName: board.selectedOptions[0]?.textContent || "",
      sprintId: Number(sprint.value), sprintName: sprint.selectedOptions[0]?.textContent || "",
    };
    const generation = beginAction(state, selection);
    resetResults(); fetchButton.textContent = "Start Over"; fetchButton.disabled = false;
    showProgress("Checking Jira access and loading tickets…");
    try {
      const { payload } = await postJson(apiFetch, "/api/automation/sprint-viewer/issues", {
        board_id: selection.boardId, sprint_id: selection.sprintId, client_action_id: state.clientActionId,
      }, state.controller.signal);
      if (!isCurrent(state, generation)) return;
      state.snapshotId = payload.snapshot_id; state.viewId = payload.view_id;
      await poll(generation, payload);
    } catch (error) {
      if (error.name !== "AbortError") showMessage("danger", errorText(error, "Unable to start the sprint report."));
      fetchButton.textContent = "Fetch Issues"; updateControls(); showProgress("");
    }
  }

  async function retryMetricFailure() {
    const failed = ["original_commitment", "completed_original", "total_completed", "added_scope", "removed_scope", "metrics"].find((key) => state.components[key]?.state === "failed");
    if (!failed) return;
    try {
      const { payload } = await postJson(apiFetch, `/api/automation/sprint-viewer/snapshots/${state.snapshotId}/retry`, {
        view_id: state.viewId, component: failed, client_action_id: crypto.randomUUID(),
      }, state.controller.signal);
      showProgress("Retrying metrics…");
      await applyStatus(payload, state.actionGeneration);
      poll(state.actionGeneration);
    } catch (error) { showMessage("warning", errorText(error, "Unable to retry metrics.")); }
  }

  async function authorizeAndExport() {
    if (!state.snapshotId || !state.core || !state.metrics) return;
    download.disabled = true; download.textContent = "Checking access…";
    const actionId = crypto.randomUUID();
    try {
      const { payload } = await postJson(apiFetch, `/api/automation/sprint-viewer/snapshots/${state.snapshotId}/authorize`, { client_action_id: actionId, purpose: "export" }, state.controller.signal);
      const exportView = payload.view_id;
      let status = payload;
      for (let attempt = 0; attempt < 60 && !status.export_ready; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, pollDelay(Math.min(attempt, 3))));
        ({ payload: status } = await getJson(apiFetch, `/api/automation/sprint-viewer/snapshots/${state.snapshotId}/status?view_id=${encodeURIComponent(exportView)}`, state.controller.signal));
        if (status.access?.core === "denied" || status.access?.metrics === "denied") throw new Error("Jira access changed; export was cancelled.");
      }
      if (!status.export_ready) throw new Error("Export authorization timed out. Try again.");
      const { payload: manifest } = await getJson(apiFetch, `/api/automation/sprint-viewer/snapshots/${state.snapshotId}/export-manifest?view_id=${encodeURIComponent(exportView)}`, state.controller.signal);
      download.textContent = "Building report…";
      const worker = new Worker(new URL("./export.worker.js", import.meta.url), { type: "module" });
      const result = await new Promise((resolve, reject) => {
        worker.onmessage = (event) => event.data.ok ? resolve(event.data.bytes) : reject(new Error(event.data.message));
        worker.onerror = reject;
        worker.postMessage({ manifest, selection: state.selection, core: state.core, metrics: state.metrics, issues: Array.from(state.issues.values()) });
      });
      worker.terminate(); downloadWorkbook(result, state.selection.sprintName);
    } catch (error) { showMessage("warning", errorText(error, "Unable to export the report.")); }
    finally { download.textContent = "Download Report"; download.disabled = false; }
  }

  project.addEventListener("change", () => { beginAction(state, null); resetResults(); populateBoards(); fetchButton.textContent = "Fetch Issues"; });
  board.addEventListener("change", () => { beginAction(state, null); resetResults(); sprint.replaceChildren(option("", "-- Select Sprint --")); updateControls(); if (board.value) loadSprints(false); });
  sprint.addEventListener("change", () => { resetResults(); fetchButton.textContent = "Fetch Issues"; updateControls(); });
  refresh.addEventListener("click", () => loadSprints(true));
  fetchButton.addEventListener("click", () => {
    if (fetchButton.textContent.trim() === "Start Over") {
      if (window.confirm("Start over and clear the displayed sprint report?")) { disposeAction(state); resetResults(); fetchButton.textContent = "Fetch Issues"; updateControls(); }
    } else startReport();
  });
  retryMetrics?.addEventListener("click", retryMetricFailure);
  download.addEventListener("click", authorizeAndExport);
  updateControls();

  disposeCurrent = () => { disposeAction(state); page.dataset.sprintViewerInitialized = "false"; };
  window.addEventListener("pagehide", disposeCurrent, { once: true });
  return disposeCurrent;
}

export function disposeSprintViewer() {
  if (disposeCurrent) disposeCurrent();
}
