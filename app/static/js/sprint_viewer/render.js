const byId = (id) => document.getElementById(id);

export function showMessage(kind, message) {
  const box = byId("msgBox");
  box.replaceChildren();
  const alert = document.createElement("div");
  alert.className = `alert alert-${kind}`;
  alert.setAttribute("role", "alert");
  alert.textContent = message;
  box.appendChild(alert);
}

export function showProgress(message) {
  const region = byId("sprintViewerProgress");
  if (!region) return;
  region.textContent = message || "";
  region.classList.toggle("d-none", !message);
}

export function resetResults() {
  byId("resultsCard").classList.add("d-none");
  byId("assigneeAccordion").replaceChildren();
  byId("metricsBox").classList.add("d-none");
  byId("workTypeMixBox").classList.add("d-none");
  byId("statsBox").classList.add("d-none");
  byId("downloadSprintReportBtn").disabled = true;
  showProgress("");
}

function textCell(row, value, className = "") {
  const cell = document.createElement("td");
  if (className) cell.className = className;
  cell.textContent = value ?? "";
  row.appendChild(cell);
}

function issueLink(key, jiraBaseUrl) {
  const link = document.createElement("a");
  link.href = `${jiraBaseUrl}/browse/${encodeURIComponent(key)}`;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = key;
  return link;
}

function appendRows(tbody, issues, jiraBaseUrl, scopeKeys, start = 0) {
  const end = Math.min(start + 50, issues.length);
  for (let index = start; index < end; index += 1) {
    const issue = issues[index];
    const row = document.createElement("tr");
    row.dataset.issueId = issue.issue_id || issue.issue_key || "";
    const keyCell = document.createElement("td");
    keyCell.className = "col-key nowrap";
    if (issue.issue_key) {
      keyCell.appendChild(issueLink(issue.issue_key, jiraBaseUrl));
      if (scopeKeys.has(issue.issue_key)) {
        const star = document.createElement("span");
        star.className = "scope-star";
        star.title = "Added after sprint start";
        star.textContent = "*";
        keyCell.appendChild(star);
      }
    }
    row.appendChild(keyCell);
    textCell(row, issue.summary);
    textCell(row, issue.issue_type);
    textCell(row, issue.status);
    textCell(row, issue.story_points);
    const featureCell = document.createElement("td");
    if (issue.feature_key) featureCell.appendChild(issueLink(issue.feature_key, jiraBaseUrl));
    row.appendChild(featureCell);
    textCell(row, issue.relevant_comment_count ?? "…");
    textCell(row, issue.historical_fallback ? "Current fallback" : "Sprint-end");
    tbody.appendChild(row);
  }
  if (end < issues.length) requestAnimationFrame(() => appendRows(tbody, issues, jiraBaseUrl, scopeKeys, end));
}

export function renderCore(data, jiraBaseUrl, expanded = new Set(), scopeKeys = new Set()) {
  byId("resultsCard").classList.remove("d-none");
  byId("totalIssues").textContent = data.total ?? 0;
  byId("totalSp").textContent = data.total_sp ?? 0;
  byId("standardTotal").textContent = data.standard_total ?? 0;
  const sprint = data.sprint || {};
  byId("sprintName").textContent = sprint.name || "-";
  byId("sprintStartDate").textContent = String(sprint.start_date || "-").slice(0, 10);
  byId("sprintActualStartDate").textContent = String(sprint.activated_date || "-").slice(0, 10);
  byId("sprintEndDate").textContent = String(sprint.end_date || "-").slice(0, 10);
  byId("sprintActualEndDate").textContent = String(sprint.complete_date || "-").slice(0, 10);
  byId("sprintGoal").textContent = sprint.goal || "-";
  byId("sprintMetaBox").classList.remove("d-none");
  renderStats(data.stats || {});
  renderWorkType(data.work_type_mix || {});
  const accordion = byId("assigneeAccordion");
  accordion.replaceChildren();
  (data.groups || []).forEach((group, index) => {
    const groupId = String(group.principal_id || group.assignee_eid || `group-${index}`).replace(/[^a-zA-Z0-9_-]/g, "-");
    const item = document.createElement("div"); item.className = "accordion-item";
    const header = document.createElement("h2"); header.className = "accordion-header";
    const button = document.createElement("button");
    button.className = `accordion-button${expanded.has(groupId) ? "" : " collapsed"}`;
    button.type = "button"; button.dataset.bsToggle = "collapse"; button.dataset.bsTarget = `#sv-${groupId}`;
    button.textContent = `${group.assignee_name || "Unassigned"} — ${group.issue_count ?? 0} issues, ${group.sp_sum ?? 0} pts`;
    header.appendChild(button);
    const collapse = document.createElement("div"); collapse.id = `sv-${groupId}`;
    collapse.className = `accordion-collapse collapse${expanded.has(groupId) ? " show" : ""}`;
    const body = document.createElement("div"); body.className = "accordion-body table-responsive";
    const table = document.createElement("table"); table.className = "table table-sm table-striped align-middle";
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    ["Key", "Summary", "Type", "Status", "Pts", "Feature Key", "Relevant Comments", "Data"].forEach((label) => { const th = document.createElement("th"); th.textContent = label; headRow.appendChild(th); });
    head.appendChild(headRow); table.appendChild(head);
    const tbody = document.createElement("tbody"); table.appendChild(tbody); body.appendChild(table); collapse.appendChild(body);
    let rendered = false;
    const render = () => { if (!rendered) { rendered = true; expanded.add(groupId); appendRows(tbody, group.issues || [], jiraBaseUrl, scopeKeys); } };
    collapse.addEventListener("show.bs.collapse", render, { once: true });
    if (expanded.has(groupId)) render();
    item.append(header, collapse); accordion.appendChild(item);
  });
}

export function renderStats(stats) {
  byId("statsBox").classList.remove("d-none");
  const mapping = {
    unestimatedCount: "unestimated_count", unestimatedPct: "unestimated_pct",
    bugCount: "bug_count", bugPct: "bug_pct", bugSp: "bug_sp",
    unassignedCount: "unassigned_count", unassignedPct: "unassigned_pct",
    zeroRelevantCommentCount: "zero_relevant_comment_count",
    zeroRelevantCommentPct: "zero_relevant_comment_pct",
    relevantCommentCount: "relevant_comment_count", carryoverCount: "carryover_count", carryoverPts: "carryover_sp",
  };
  Object.entries(mapping).forEach(([id, key]) => { byId(id).textContent = stats[key] ?? "—"; });
}

export function renderWorkType(mix) {
  const box = byId("workTypeMixBox"); box.classList.remove("d-none");
  const overall = byId("workTypeOverall"); overall.replaceChildren();
  Object.entries(mix.overall || {}).forEach(([name, bucket]) => { const el = document.createElement("div"); el.className = "sv-stat"; el.textContent = `${name}: ${bucket.count ?? 0} #, ${bucket.pts ?? 0} pts`; overall.appendChild(el); });
  const tbody = byId("workTypeByDeveloper"); tbody.replaceChildren();
  (mix.by_assignee || []).forEach((item) => { const row = document.createElement("tr"); textCell(row, item.assignee_name || item.assignee_eid); textCell(row, Object.entries(item.types || {}).map(([name, bucket]) => `${name}: ${bucket.count} #, ${bucket.pts} pts`).join("; ")); tbody.appendChild(row); });
}

export function renderMetrics(metrics) {
  byId("metricsBox").classList.remove("d-none");
  const pair = (count, points) => (count == null || points == null ? "—" : `${count} # (${Number(points).toFixed(2)} pts)`);
  const values = {
    committedFmt: pair(metrics.committed_count, metrics.committed_sp),
    completedOriginalFmt: pair(metrics.completed_original_count, metrics.completed_original_sp),
    deliveredFmt: pair(metrics.delivered_count, metrics.delivered_sp),
    spilloverFmt: pair(metrics.spillover_count, metrics.spillover_sp),
    scopeAddedFmt: pair(metrics.scope_added_count, metrics.scope_added_sp),
    descopeFmt: pair(metrics.descope_count, metrics.descope_sp),
    scopeNetFmt: pair(metrics.scope_net_count, metrics.scope_net_sp),
    scopePct: metrics.scope_pct ?? "—", predictabilityPct: metrics.predictability_pct ?? "—",
    totalDeliveryPct: metrics.total_delivery_vs_commitment_pct ?? "—", scopeChangePct: metrics.scope_change_pct ?? "—",
  };
  Object.entries(values).forEach(([id, value]) => { byId(id).textContent = value; });
  const basis = byId("metricTimeBasis"); if (basis) basis.textContent = metrics.time_basis || "Jira points at collection time";
}

export function setMetricsPending() {
  byId("metricsBox").classList.remove("d-none");
  ["committedFmt", "completedOriginalFmt", "deliveredFmt", "spilloverFmt", "scopeAddedFmt", "descopeFmt", "scopeNetFmt", "scopePct", "predictabilityPct", "totalDeliveryPct", "scopeChangePct"].forEach((id) => { byId(id).textContent = "…"; });
}
