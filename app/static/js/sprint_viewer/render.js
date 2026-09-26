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
  delete byId("assigneeAccordion").dataset.initialized;
  byId("metricsBox").classList.add("d-none");
  byId("workTypeMixBox").classList.add("d-none");
  byId("statsBox").classList.add("d-none");
  byId("downloadSprintReportBtn").disabled = true;
  showProgress("");
}

function parseDate(value) {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatIst(value, includeTime = true) {
  const parsed = parseDate(value);
  if (!parsed) return "—";
  const options = { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric" };
  if (includeTime) Object.assign(options, { hour: "2-digit", minute: "2-digit", hour12: true });
  return `${new Intl.DateTimeFormat("en-IN", options).format(parsed)}${includeTime ? " IST" : ""}`;
}

function durationLabel(start, end) {
  const first = parseDate(start); const last = parseDate(end);
  if (!first || !last || last < first) return "—";
  const days = Math.max(1, Math.ceil((last - first) / 86400000));
  return `${days} ${days === 1 ? "day" : "days"}`;
}

function completedKeys(metrics) {
  return new Set(Array.isArray(metrics?.completed_keys) ? metrics.completed_keys : []);
}

function isCompletedIssue(issue, keys = new Set()) {
  if (issue?.issue_key && keys.has(issue.issue_key)) return true;
  const category = String(issue?.status_category_key || issue?.status_category || "").trim().toLowerCase();
  if (["done", "complete", "completed"].includes(category)) return true;
  return ["done", "closed", "resolved", "complete", "completed"].includes(String(issue?.status || "").trim().toLowerCase());
}

function summarizeIssues(issues, keys = new Set()) {
  const summary = { assignedPoints: 0, assignedCount: 0, deliveredPoints: 0, deliveredCount: 0 };
  (issues || []).forEach((issue) => {
    const points = finiteNumber(issue.story_points) ?? 0;
    summary.assignedPoints += points; summary.assignedCount += 1;
    if (isCompletedIssue(issue, keys)) { summary.deliveredPoints += points; summary.deliveredCount += 1; }
  });
  return summary;
}

function textCell(row, value, className = "") {
  const cell = document.createElement("td");
  if (className) cell.className = className;
  cell.textContent = value ?? "";
  row.appendChild(cell);
}

function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function formatNumber(value, maximumFractionDigits = 2) {
  const number = finiteNumber(value);
  if (number === null) return "—";
  return new Intl.NumberFormat(undefined, { maximumFractionDigits }).format(number);
}

function formatPercent(value) {
  const number = finiteNumber(value);
  return number === null ? "—" : `${formatNumber(number, 1)}%`;
}

function setText(id, value) {
  const element = byId(id);
  if (element) element.textContent = value;
}

const workTypeColors = {
  story: "#0d6efd",
  task: "#198754",
  bug: "#dc3545",
  defect: "#dc3545",
  subtask: "#6c757d",
  "sub-task": "#6c757d",
  "sub task": "#6c757d",
};
const fallbackTypeColors = ["#6f42c1", "#0dcaf0", "#fd7e14", "#20c997", "#495057"];

function typeColor(type, index) {
  return workTypeColors[String(type || "").trim().toLowerCase()] || fallbackTypeColors[index % fallbackTypeColors.length];
}

function sortedWorkTypes(mix) {
  const names = new Set(Object.keys(mix?.overall || {}));
  (mix?.by_assignee || []).forEach((row) => Object.keys(row?.types || {}).forEach((name) => names.add(name)));
  const preferred = new Map([
    ["story", 0], ["task", 1], ["bug", 2], ["defect", 2],
    ["sub-task", 3], ["subtask", 3], ["sub task", 3], ["unknown", 99],
  ]);
  return Array.from(names).sort((left, right) => {
    const leftRank = preferred.get(String(left).toLowerCase()) ?? 10;
    const rightRank = preferred.get(String(right).toLowerCase()) ?? 10;
    return leftRank - rightRank || String(left).localeCompare(String(right));
  });
}

function sumBuckets(entries, key) {
  if (!entries.length) return 0;
  const values = entries.map(([, bucket]) => finiteNumber(bucket?.[key]));
  return values.some((value) => value === null) ? null : values.reduce((sum, value) => sum + value, 0);
}

function bucketPercent(bucket, key, value, total) {
  const supplied = finiteNumber(bucket?.[key]);
  if (supplied !== null) return supplied;
  if (value === null || total === null || total <= 0) return null;
  return (value / total) * 100;
}

function appendTypeName(cell, type, color, unestimated) {
  const label = document.createElement("span");
  label.className = "sv-type-name";
  const marker = document.createElement("span");
  marker.className = "sv-type-marker";
  marker.style.setProperty("--sv-type-color", color);
  label.append(marker, document.createTextNode(type));
  cell.appendChild(label);
  if (finiteNumber(unestimated) > 0) {
    const note = document.createElement("span");
    note.className = "sv-unestimated-note";
    note.textContent = `${formatNumber(unestimated, 0)} unestimated`;
    cell.appendChild(note);
  }
}

function appendMatrixCell(
  row,
  points,
  count,
  pointPct,
  unestimated = 0,
  percentageLabel = "of developer pts",
  showUnavailablePercentage = false
) {
  const cell = document.createElement("td");
  cell.className = "sv-matrix-value";
  if (points === null && count === null) {
    cell.textContent = "—";
    row.appendChild(cell);
    return;
  }
  const primary = document.createElement("strong");
  primary.textContent = points === null ? "—" : `${formatNumber(points)} pts`;
  const secondary = document.createElement("span");
  const parts = [count === null ? "issues unavailable" : `${formatNumber(count, 0)} ${count === 1 ? "issue" : "issues"}`];
  if (pointPct !== null) parts.push(`${formatPercent(pointPct)} ${percentageLabel}`);
  else if (showUnavailablePercentage) parts.push(`— ${percentageLabel}`);
  if (finiteNumber(unestimated) > 0) parts.push(`${formatNumber(unestimated, 0)} unestimated`);
  secondary.textContent = parts.join(" · ");
  cell.append(primary, secondary);
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

export function renderCore(data, jiraBaseUrl, expanded = new Set(), scopeKeys = new Set(), metrics = null) {
  byId("resultsCard").classList.remove("d-none");
  setText("totalIssues", data.total ?? 0); setText("qualityTotalIssues", data.total ?? 0);
  setText("totalSp", data.total_sp ?? 0); setText("standardTotal", data.standard_total ?? 0);
  const sprint = data.sprint || {};
  setText("sprintName", sprint.name || sprint.id || "—");
  setText("sprintStartDate", formatIst(sprint.start_date, false));
  setText("sprintActualStartDate", formatIst(sprint.activated_date || sprint.start_date));
  setText("sprintEndDate", formatIst(sprint.end_date, false));
  setText("sprintActualEndDate", formatIst(sprint.complete_date || sprint.end_date));
  setText("sprintDuration", durationLabel(sprint.activated_date || sprint.start_date, sprint.complete_date || sprint.end_date));
  setText("sprintGoal", sprint.goal || "No sprint goal recorded");
  const state = String(sprint.state || "closed"); setText("sprintState", state.charAt(0).toUpperCase() + state.slice(1));
  setText("reportAsOf", `As of ${formatIst(sprint.complete_date || sprint.end_date, false)}`);
  const fallbackCount = data.historical_fallback_count || 0;
  setText("historicalFallbackStatus", fallbackCount ? `${fallbackCount} current-value fallback` : "Not required");
  const fallbackNote = byId("historicalFallbackNote");
  fallbackNote.classList.toggle("d-none", !fallbackCount);
  if (fallbackCount) fallbackNote.textContent = `${fallbackCount} row(s) use current Jira values.`;
  byId("sprintMetaBox").classList.remove("d-none");
  renderStats(data.stats, data);
  renderWorkType(data.work_type_mix, data.groups || [], metrics);

  const accordion = byId("assigneeAccordion");
  const groups = data.groups || [];
  if (accordion.dataset.initialized !== "true" && groups.length) {
    expanded.add(String(groups[0].principal_id || groups[0].assignee_eid || "group-0").replace(/[^a-zA-Z0-9_-]/g, "-"));
    accordion.dataset.initialized = "true";
  }
  const statusFilter = byId("sprintStatusFilter");
  const selectedStatus = statusFilter.value;
  const statuses = [...new Set(groups.flatMap((group) => (group.issues || []).map((issue) => issue.status).filter(Boolean)))].sort();
  statusFilter.replaceChildren();
  const all = document.createElement("option"); all.value = ""; all.textContent = "All statuses"; statusFilter.appendChild(all);
  statuses.forEach((status) => { const option = document.createElement("option"); option.value = status; option.textContent = status; statusFilter.appendChild(option); });
  statusFilter.value = statuses.includes(selectedStatus) ? selectedStatus : "";
  const keys = completedKeys(metrics); const sprintDelivered = groups.reduce((sum, group) => sum + summarizeIssues(group.issues, keys).deliveredPoints, 0);
  accordion.replaceChildren();
  groups.forEach((group, index) => {
    const groupId = String(group.principal_id || group.assignee_eid || `group-${index}`).replace(/[^a-zA-Z0-9_-]/g, "-");
    const summary = summarizeIssues(group.issues, keys);
    const mixAssignee = (data.work_type_mix?.by_assignee || []).find((row) => String(row.principal_id || "").replace(/[^a-zA-Z0-9_-]/g, "-") === groupId || String(row.assignee_eid || "") === String(group.assignee_eid || ""));
    const assignedPoints = finiteNumber(mixAssignee?.total_pts) ?? summary.assignedPoints; const assignedCount = finiteNumber(mixAssignee?.total_count) ?? summary.assignedCount;
    const rate = assignedPoints > 0 ? summary.deliveredPoints / assignedPoints * 100 : (assignedCount ? summary.deliveredCount / assignedCount * 100 : null);
    const share = sprintDelivered > 0 ? summary.deliveredPoints / sprintDelivered * 100 : null;
    const item = document.createElement("div"); item.className = "accordion-item";
    const header = document.createElement("h4"); header.className = "accordion-header";
    const button = document.createElement("button");
    button.className = `accordion-button${expanded.has(groupId) ? "" : " collapsed"}`;
    button.type = "button"; button.dataset.bsToggle = "collapse"; button.dataset.bsTarget = `#sv-${groupId}`;
    const name = document.createElement("span"); name.className = "sv-accordion-name"; name.textContent = group.assignee_name || "Unassigned";
    const summaryNode = document.createElement("span"); summaryNode.className = "sv-accordion-summary";
    summaryNode.innerHTML = `<span><strong>${formatNumber(summary.deliveredPoints)}</strong> / ${formatNumber(assignedPoints)} pts</span><span><strong>${formatNumber(summary.deliveredCount, 0)}</strong> / ${formatNumber(assignedCount, 0)} issues</span><span><strong>${formatPercent(rate)}</strong> delivery</span><span><strong>${formatPercent(share)}</strong> of sprint delivery</span>`;
    button.append(name, summaryNode); header.appendChild(button);
    const collapse = document.createElement("div"); collapse.id = `sv-${groupId}`; collapse.className = `accordion-collapse collapse${expanded.has(groupId) ? " show" : ""}`;
    collapse.addEventListener("show.bs.collapse", () => expanded.add(groupId)); collapse.addEventListener("hide.bs.collapse", () => expanded.delete(groupId));
    const body = document.createElement("div"); body.className = "accordion-body table-responsive";
    const table = document.createElement("table"); table.className = "table table-sm align-middle sv-issue-table";
    const head = document.createElement("thead"); const headRow = document.createElement("tr");
    ["Issue key", "Summary", "Type", "Status at close", "Outcome", "Points", "Feature / Epic", "Relevant comments", "Data basis"].forEach((label) => { const th = document.createElement("th"); th.scope = "col"; th.textContent = label; headRow.appendChild(th); });
    head.appendChild(headRow); table.appendChild(head); const tbody = document.createElement("tbody");
    const visible = (group.issues || []).filter((issue) => !statusFilter.value || issue.status === statusFilter.value);
    visible.forEach((issue) => {
      const delivered = isCompletedIssue(issue, keys); const row = document.createElement("tr");
      const keyCell = document.createElement("td"); keyCell.className = "nowrap";
      if (issue.issue_key) { keyCell.appendChild(issueLink(issue.issue_key, jiraBaseUrl)); if (scopeKeys.has(issue.issue_key)) { const star = document.createElement("span"); star.className = "scope-star"; star.textContent = "*"; star.title = "Added after sprint start"; keyCell.appendChild(star); } }
      row.appendChild(keyCell); textCell(row, issue.summary); textCell(row, issue.issue_type);
      const statusCell = document.createElement("td"); const statusPill = document.createElement("span"); statusPill.className = `sv-status ${delivered ? "sv-status-done" : "sv-status-open"}`; statusPill.textContent = issue.status || "—"; statusCell.appendChild(statusPill); row.appendChild(statusCell);
      const outcomeCell = document.createElement("td"); const outcome = document.createElement("span"); outcome.className = `sv-outcome-pill ${delivered ? "sv-outcome-completed" : "sv-outcome-unfinished"}`; outcome.textContent = delivered ? "Completed" : "Unfinished"; outcomeCell.appendChild(outcome); row.appendChild(outcomeCell);
      textCell(row, formatNumber(issue.story_points)); const feature = document.createElement("td"); if (issue.feature_key) feature.appendChild(issueLink(issue.feature_key, jiraBaseUrl)); else feature.textContent = "—"; row.appendChild(feature);
      textCell(row, issue.relevant_comment_count ?? "…"); textCell(row, issue.historical_fallback ? "Current fallback" : "Sprint-end", "sv-data-basis"); tbody.appendChild(row);
    });
    if (!visible.length) { const row = document.createElement("tr"); const cell = document.createElement("td"); cell.colSpan = 9; cell.className = "sv-filter-empty"; cell.textContent = "No tickets match the selected status."; row.appendChild(cell); tbody.appendChild(row); }
    table.appendChild(tbody); body.appendChild(table); collapse.appendChild(body); item.append(header, collapse); accordion.appendChild(item);
  });
  statusFilter.onchange = () => renderCore(data, jiraBaseUrl, expanded, scopeKeys, metrics);
  byId("expandAllDevelopersBtn").onclick = () => accordion.querySelectorAll(".accordion-collapse").forEach((element) => window.bootstrap?.Collapse?.getOrCreateInstance(element, { toggle: false })?.show());
  byId("collapseAllDevelopersBtn").onclick = () => accordion.querySelectorAll(".accordion-collapse").forEach((element) => window.bootstrap?.Collapse?.getOrCreateInstance(element, { toggle: false })?.hide());
}

export function renderStats(stats, context = {}, options = {}) {
  const values = stats && typeof stats === "object" ? stats : {};
  byId("statsBox").classList.remove("d-none");
  const total = finiteNumber(context.standard_total);
  const totalPoints = finiteNumber(context.total_sp);
  const unestimated = finiteNumber(values.unestimated_count);
  const unestimatedPct = finiteNumber(values.unestimated_pct);
  const estimated = total !== null && unestimated !== null ? Math.max(total - unestimated, 0) : null;
  setText("estimationCoverageValue", formatPercent(total && estimated !== null ? (estimated / total) * 100 : null));
  setText("estimatedIssueCount", formatNumber(estimated, 0));
  setText("estimationTotalCount", formatNumber(total, 0));
  setText("unestimatedCount", formatNumber(unestimated, 0));
  setText("unestimatedPct", formatNumber(unestimatedPct, 1));
  setText("healthUnestimated", formatNumber(unestimated, 0));

  const unassigned = finiteNumber(values.unassigned_count);
  const unassignedPct = finiteNumber(values.unassigned_pct);
  const assigned = total !== null && unassigned !== null ? Math.max(total - unassigned, 0) : null;
  setText("ownershipCoverageValue", formatPercent(total && assigned !== null ? (assigned / total) * 100 : null));
  setText("assignedIssueCount", formatNumber(assigned, 0));
  setText("ownershipTotalCount", formatNumber(total, 0));
  setText("unassignedCount", formatNumber(unassigned, 0));
  setText("unassignedPct", formatNumber(unassignedPct, 1));
  setText("healthUnassigned", formatNumber(unassigned, 0));

  const defectCount = finiteNumber(values.bug_count);
  const defectPoints = finiteNumber(values.bug_sp);
  const defectPointPct = totalPoints === null || defectPoints === null
    ? null
    : totalPoints > 0 ? (defectPoints / totalPoints) * 100 : 0;
  setText("bugCount", formatNumber(defectCount, 0));
  setText("bugSp", formatNumber(defectPoints));
  setText("bugPct", formatNumber(values.bug_pct, 1));
  setText("bugPointPct", formatNumber(defectPointPct, 1));

  const zeroRelevant = finiteNumber(values.zero_relevant_comment_count);
  const zeroRelevantPct = finiteNumber(values.zero_relevant_comment_pct);
  const relevantComments = finiteNumber(values.relevant_comment_count);
  if (options.commentsUnavailable) {
    setText("commentCoverageValue", "Unavailable");
    setText("commentCoverageMeta", "Relevant-comment metrics could not be loaded");
    setText("relevantCommentCount", "Unavailable");
    setText("relevantCommentsMeta", "Issue and work-breakdown data is still available");
  } else if (zeroRelevant === null || zeroRelevantPct === null || relevantComments === null) {
    setText("commentCoverageValue", "Calculating…");
    setText("commentCoverageMeta", "Relevant comments are loading in the background");
    setText("relevantCommentCount", "Calculating…");
    setText("relevantCommentsMeta", "By the assigned developer during the sprint window");
  } else {
    setText("commentCoverageValue", formatPercent(Math.max(100 - zeroRelevantPct, 0)));
    setText("commentCoverageMeta", `${formatNumber(zeroRelevant, 0)} issues need a relevant comment · ${formatPercent(zeroRelevantPct)} gap`);
    setText("relevantCommentCount", formatNumber(relevantComments, 0));
    setText("relevantCommentsMeta", "By the assigned developer during the sprint window");
  }
  setText("zeroRelevantCommentCount", formatNumber(zeroRelevant, 0));
  setText("zeroRelevantCommentPct", formatNumber(zeroRelevantPct, 1));
  setText("carryoverCount", formatNumber(values.carryover_count, 0));
  setText("carryoverPts", formatNumber(values.carryover_sp));
  setText("healthCarryover", `${formatNumber(values.carryover_count, 0)} issues`);
}

function appendDeliveryCell(row, delivered, assigned, sprintDeliveredPoints, showSprintShare = false) {
  const cell = document.createElement("td"); cell.className = "sv-matrix-value";
  if (!assigned || (!assigned.assignedCount && !assigned.assignedPoints)) { cell.textContent = "—"; row.appendChild(cell); return; }
  const deliveredPoints = delivered?.deliveredPoints ?? 0; const deliveredCount = delivered?.deliveredCount ?? 0;
  const rate = assigned.assignedPoints > 0 ? deliveredPoints / assigned.assignedPoints * 100 : (assigned.assignedCount ? deliveredCount / assigned.assignedCount * 100 : null);
  const primary = document.createElement("span"); primary.className = "sv-matrix-primary"; primary.textContent = `${formatNumber(deliveredPoints)} / ${formatNumber(assigned.assignedPoints)} pts · ${formatNumber(deliveredCount, 0)} / ${formatNumber(assigned.assignedCount, 0)} issues`;
  const secondary = document.createElement("span"); secondary.className = "sv-matrix-secondary";
  const parts = [`${formatPercent(rate)} delivery`]; if (showSprintShare) parts.push(`${formatPercent(sprintDeliveredPoints > 0 ? deliveredPoints / sprintDeliveredPoints * 100 : null)} of sprint delivery`); secondary.textContent = parts.join(" · ");
  const progress = document.createElement("span"); progress.className = "sv-progress"; progress.setAttribute("role", "progressbar"); progress.setAttribute("aria-valuenow", String(Math.round(rate || 0))); progress.setAttribute("aria-valuemin", "0"); progress.setAttribute("aria-valuemax", "100");
  const fill = document.createElement("span"); fill.style.width = `${Math.min(Math.max(rate || 0, 0), 100)}%`; progress.appendChild(fill); cell.append(primary, secondary, progress); row.appendChild(cell);
}

export function renderWorkType(mix, groups = [], metrics = null) {
  const box = byId("workTypeMixBox"); box.classList.remove("d-none");
  const unavailable = byId("workTypeUnavailable"); const content = byId("workTypeContent"); const totals = byId("workTypeTotals");
  const types = sortedWorkTypes(mix); const assignees = Array.isArray(mix?.by_assignee) ? mix.by_assignee : [];
  if (!mix || !types.length || !assignees.length) {
    unavailable.textContent = "Work-distribution metrics are unavailable. Sprint tickets can still be reviewed below."; unavailable.classList.remove("d-none"); content.classList.add("d-none"); totals.classList.add("d-none"); return;
  }
  unavailable.classList.add("d-none"); content.classList.remove("d-none"); totals.classList.remove("d-none");
  const keys = completedKeys(metrics); const allIssues = groups.flatMap((group) => group.issues || []); const team = summarizeIssues(allIssues, keys);
  const teamAssigned = { assignedPoints: finiteNumber(mix.totals?.pts) ?? team.assignedPoints, assignedCount: finiteNumber(mix.totals?.count) ?? team.assignedCount };
  setText("workTypeDeliveredPoints", formatNumber(team.deliveredPoints)); setText("workTypeTotalPoints", formatNumber(teamAssigned.assignedPoints)); setText("workTypeDeliveredCount", formatNumber(team.deliveredCount, 0)); setText("workTypeTotalCount", formatNumber(teamAssigned.assignedCount, 0));
  const cards = byId("workTypeCards"); cards.replaceChildren();
  types.forEach((type, index) => {
    const issues = allIssues.filter((issue) => (issue.issue_type || "Unknown") === type); const summary = summarizeIssues(issues, keys); const bucket = mix.overall?.[type] || {};
    const assigned = { assignedPoints: finiteNumber(bucket.pts) ?? summary.assignedPoints, assignedCount: finiteNumber(bucket.count) ?? summary.assignedCount };
    const rate = assigned.assignedPoints > 0 ? summary.deliveredPoints / assigned.assignedPoints * 100 : (assigned.assignedCount ? summary.deliveredCount / assigned.assignedCount * 100 : null);
    const item = document.createElement("article"); item.className = "sv-work-type-item";
    const title = document.createElement("div"); title.className = "sv-work-type-title"; const marker = document.createElement("span"); marker.className = "sv-type-marker"; marker.style.setProperty("--sv-type-color", typeColor(type, index)); title.append(marker, document.createTextNode(type));
    const values = document.createElement("div"); values.className = "sv-work-type-values"; values.innerHTML = `<strong>${formatNumber(summary.deliveredPoints)} / ${formatNumber(assigned.assignedPoints)} pts</strong> · ${formatNumber(summary.deliveredCount, 0)} / ${formatNumber(assigned.assignedCount, 0)} issues · <strong>${formatPercent(rate)}</strong>`;
    const progress = document.createElement("div"); progress.className = "sv-progress"; progress.setAttribute("role", "progressbar"); progress.setAttribute("aria-label", `${type} delivery rate`); progress.setAttribute("aria-valuenow", String(Math.round(rate || 0))); progress.setAttribute("aria-valuemin", "0"); progress.setAttribute("aria-valuemax", "100"); const fill = document.createElement("span"); fill.style.width = `${Math.min(Math.max(rate || 0, 0), 100)}%`; progress.appendChild(fill); item.append(title, values, progress); cards.appendChild(item);
  });
  const head = byId("workTypeByDeveloperHead"); head.replaceChildren(); const headRow = document.createElement("tr"); ["Developer", "Total", ...types].forEach((label) => { const th = document.createElement("th"); th.scope = "col"; th.textContent = label; headRow.appendChild(th); }); head.appendChild(headRow);
  const groupByKey = new Map(); groups.forEach((group) => { groupByKey.set(String(group.principal_id || group.assignee_eid || "UNASSIGNED"), group); if (group.assignee_eid) groupByKey.set(String(group.assignee_eid), group); }); const tbody = byId("workTypeByDeveloper"); tbody.replaceChildren();
  assignees.forEach((assignee) => {
    const issues = groupByKey.get(String(assignee.principal_id || assignee.assignee_eid || "UNASSIGNED"))?.issues || []; const row = document.createElement("tr"); textCell(row, assignee.assignee_name || assignee.assignee_eid || "Unassigned", "sv-developer-name"); appendDeliveryCell(row, summarizeIssues(issues, keys), { assignedPoints: finiteNumber(assignee.total_pts) ?? summarizeIssues(issues).assignedPoints, assignedCount: finiteNumber(assignee.total_count) ?? summarizeIssues(issues).assignedCount }, team.deliveredPoints, true);
    types.forEach((type) => { const typed = issues.filter((issue) => (issue.issue_type || "Unknown") === type); const bucket = assignee.types?.[type] || {}; appendDeliveryCell(row, summarizeIssues(typed, keys), { assignedPoints: finiteNumber(bucket.pts) ?? summarizeIssues(typed).assignedPoints, assignedCount: finiteNumber(bucket.count) ?? summarizeIssues(typed).assignedCount }, team.deliveredPoints); }); tbody.appendChild(row);
  });
  const foot = byId("workTypeByDeveloperTotal"); foot.replaceChildren(); const totalRow = document.createElement("tr"); const label = document.createElement("th"); label.scope = "row"; label.textContent = "Team total"; totalRow.appendChild(label); appendDeliveryCell(totalRow, team, teamAssigned, team.deliveredPoints, true);
  types.forEach((type) => { const typed = allIssues.filter((issue) => (issue.issue_type || "Unknown") === type); const bucket = mix.overall?.[type] || {}; appendDeliveryCell(totalRow, summarizeIssues(typed, keys), { assignedPoints: finiteNumber(bucket.pts) ?? summarizeIssues(typed).assignedPoints, assignedCount: finiteNumber(bucket.count) ?? summarizeIssues(typed).assignedCount }, team.deliveredPoints); }); foot.appendChild(totalRow);
}

export function initMetricHelp(root = document) {
  const Tooltip = window.bootstrap?.Tooltip;
  if (!Tooltip) return;
  root.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((control) => {
    Tooltip.getOrCreateInstance(control, {
      container: "body",
      customClass: "sv-metric-tooltip",
    });
  });
}

export function renderMetrics(metrics, core = null) {
  const metricValues = metrics && typeof metrics === "object" ? metrics : {};
  byId("metricsBox").classList.remove("d-none");
  const hasMetrics = [
    "committed_count", "committed_sp", "completed_original_count", "completed_original_sp",
    "delivered_count", "delivered_sp", "spillover_count", "spillover_sp",
  ].some((key) => finiteNumber(metricValues[key]) !== null);
  byId("metricsUnavailableMessage")?.classList.toggle("d-none", hasMetrics);
  const pair = (count, points) => (
    finiteNumber(count) === null || finiteNumber(points) === null
      ? "—"
      : `${formatNumber(count, 0)} issues · ${formatNumber(points)} pts`
  );
  const rendered = {
    committedFmt: pair(metricValues.committed_count, metricValues.committed_sp),
    completedOriginalFmt: pair(metricValues.completed_original_count, metricValues.completed_original_sp),
    deliveredFmt: pair(metricValues.delivered_count, metricValues.delivered_sp),
    spilloverFmt: pair(metricValues.spillover_count, metricValues.spillover_sp),
    scopeAddedFmt: pair(metricValues.scope_added_count, metricValues.scope_added_sp),
    descopeFmt: pair(metricValues.descope_count, metricValues.descope_sp),
    scopeNetFmt: pair(metricValues.scope_net_count, metricValues.scope_net_sp),
    scopePct: formatNumber(metricValues.scope_pct, 1), predictabilityPct: formatNumber(metricValues.predictability_pct, 1),
    totalDeliveryPct: formatNumber(metricValues.total_delivery_vs_commitment_pct, 1), scopeChangePct: formatNumber(metricValues.scope_change_pct, 1),
  };
  Object.entries(rendered).forEach(([id, value]) => { byId(id).textContent = value; });
  const basis = byId("metricTimeBasis"); if (basis) basis.textContent = metricValues.time_basis || "Jira points at collection time";
  setText("healthAddedScope", `${formatNumber(metricValues.scope_added_count, 0)} issues`);
  setText("healthPredictability", formatPercent(metricValues.predictability_pct));
  setText("healthCarryover", `${formatNumber(metricValues.spillover_count, 0)} issues`);
  const issues = (core?.groups || []).flatMap((group) => group.issues || []); const team = summarizeIssues(issues, completedKeys(metricValues));
  const assignedPoints = finiteNumber(core?.work_type_mix?.totals?.pts) ?? team.assignedPoints; const assignedCount = finiteNumber(core?.work_type_mix?.totals?.count) ?? team.assignedCount;
  const teamRate = assignedPoints > 0 ? team.deliveredPoints / assignedPoints * 100 : (assignedCount ? team.deliveredCount / assignedCount * 100 : null); setText("teamDeliveryRate", formatPercent(teamRate));
  const completed = finiteNumber(metricValues.delivered_count) ?? 0; const unfinished = finiteNumber(metricValues.spillover_count) ?? 0; const removed = finiteNumber(metricValues.descope_count) ?? 0; const total = completed + unfinished + removed;
  [["outcomeCompletedSegment", "outcomeCompletedLabel", completed], ["outcomeUnfinishedSegment", "outcomeUnfinishedLabel", unfinished], ["outcomeRemovedSegment", "outcomeRemovedLabel", removed]].forEach(([segmentId, labelId, count]) => {
    const pct = total > 0 ? count / total * 100 : 0; const segment = byId(segmentId); segment.style.width = `${pct}%`; segment.textContent = pct >= 10 ? `${formatNumber(count, 0)} (${formatPercent(pct)})` : ""; setText(labelId, `${formatNumber(count, 0)} (${formatPercent(pct)})`);
  });
  byId("sprintOutcomeBar").setAttribute("aria-label", `Sprint outcome: ${formatNumber(completed, 0)} completed, ${formatNumber(unfinished, 0)} unfinished, ${formatNumber(removed, 0)} removed.`);
}

export function setMetricsPending() {
  byId("metricsBox").classList.remove("d-none");
  byId("metricsUnavailableMessage")?.classList.add("d-none");
  ["committedFmt", "completedOriginalFmt", "deliveredFmt", "spilloverFmt", "scopeAddedFmt", "descopeFmt", "scopeNetFmt", "scopePct", "predictabilityPct", "totalDeliveryPct", "scopeChangePct"].forEach((id) => { byId(id).textContent = "…"; });
}
