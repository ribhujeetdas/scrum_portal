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
  renderStats(data.stats, data);
  renderWorkType(data.work_type_mix);
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
    const render = () => {
      expanded.add(groupId);
      if (!rendered) {
        rendered = true;
        appendRows(tbody, group.issues || [], jiraBaseUrl, scopeKeys);
      }
    };
    collapse.addEventListener("show.bs.collapse", render);
    collapse.addEventListener("hide.bs.collapse", () => expanded.delete(groupId));
    if (expanded.has(groupId)) render();
    item.append(header, collapse); accordion.appendChild(item);
  });
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

  const unassigned = finiteNumber(values.unassigned_count);
  const unassignedPct = finiteNumber(values.unassigned_pct);
  const assigned = total !== null && unassigned !== null ? Math.max(total - unassigned, 0) : null;
  setText("ownershipCoverageValue", formatPercent(total && assigned !== null ? (assigned / total) * 100 : null));
  setText("assignedIssueCount", formatNumber(assigned, 0));
  setText("ownershipTotalCount", formatNumber(total, 0));
  setText("unassignedCount", formatNumber(unassigned, 0));
  setText("unassignedPct", formatNumber(unassignedPct, 1));

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
}

export function renderWorkType(mix) {
  const box = byId("workTypeMixBox");
  box.classList.remove("d-none");
  const unavailable = byId("workTypeUnavailable");
  const content = byId("workTypeContent");
  const totals = byId("workTypeTotals");
  if (!mix || typeof mix !== "object") {
    unavailable.textContent = "Work-breakdown metrics are unavailable. Sprint issues can still be reviewed below.";
    unavailable.classList.remove("d-none");
    content.classList.add("d-none");
    totals.classList.add("d-none");
    return;
  }
  const types = sortedWorkTypes(mix);
  const overallEntries = types.map((type) => [type, mix.overall?.[type] || null]);
  if (!types.length) {
    unavailable.textContent = "No work-type data was returned for this sprint.";
    unavailable.classList.remove("d-none");
    content.classList.add("d-none");
    totals.classList.add("d-none");
    return;
  }
  unavailable.classList.add("d-none");
  content.classList.remove("d-none");
  totals.classList.remove("d-none");
  const totalCount = finiteNumber(mix.totals?.count) ?? sumBuckets(overallEntries, "count");
  const totalPoints = finiteNumber(mix.totals?.pts) ?? sumBuckets(overallEntries, "pts");
  const totalUnestimated = finiteNumber(mix.totals?.unestimated_count) ?? sumBuckets(overallEntries, "unestimated_count");
  setText("workTypeTotalCount", formatNumber(totalCount, 0));
  setText("workTypeTotalPoints", formatNumber(totalPoints));

  const pointBar = byId("workTypePointBar");
  const pointLegend = byId("workTypePointLegend");
  pointBar.replaceChildren();
  pointLegend.replaceChildren();
  const distributionLabels = [];
  overallEntries.forEach(([type, bucket], index) => {
    const points = finiteNumber(bucket?.pts);
    const pct = bucketPercent(bucket, "points_pct", points, totalPoints);
    const value = points === null ? "—" : `${formatNumber(points)} pts · ${formatPercent(pct)}`;
    distributionLabels.push(`${type}: ${value}`);
    const legendItem = document.createElement("span");
    legendItem.className = "sv-point-legend-item";
    const marker = document.createElement("span");
    marker.className = "sv-type-marker";
    marker.style.setProperty("--sv-type-color", typeColor(type, index));
    const label = document.createElement("strong");
    label.textContent = type;
    legendItem.append(marker, label, document.createTextNode(` · ${value}`));
    pointLegend.appendChild(legendItem);
  });
  pointBar.setAttribute("aria-label", `Point distribution by Jira issue type. ${distributionLabels.join("; ")}`);
  if (totalPoints !== null && totalPoints > 0) {
    overallEntries.forEach(([type, bucket], index) => {
      const points = finiteNumber(bucket?.pts);
      if (points === null || points <= 0) return;
      const pct = bucketPercent(bucket, "points_pct", points, totalPoints);
      const segment = document.createElement("span");
      segment.className = "sv-point-segment";
      segment.style.width = `${Math.max(pct || 0, 0)}%`;
      segment.style.setProperty("--sv-type-color", typeColor(type, index));
      segment.title = `${type}: ${formatNumber(points)} pts (${formatPercent(pct)})`;
      segment.setAttribute("aria-label", segment.title);
      segment.textContent = pct >= 18 ? `${type} · ${formatNumber(points)} pts · ${formatPercent(pct)}` : "";
      pointBar.appendChild(segment);
    });
  } else {
    const empty = document.createElement("span");
    empty.className = "sv-point-bar-empty";
    empty.textContent = totalUnestimated > 0
      ? "Point distribution unavailable — no mapped estimates were returned."
      : "No points were recorded for this sprint.";
    pointBar.appendChild(empty);
  }

  const overall = byId("workTypeOverall");
  const overallTotal = byId("workTypeOverallTotal");
  overall.replaceChildren();
  overallTotal.replaceChildren();
  overallEntries.forEach(([type, bucket], index) => {
    const row = document.createElement("tr");
    const nameCell = document.createElement("td");
    appendTypeName(nameCell, type, typeColor(type, index), bucket?.unestimated_count);
    row.appendChild(nameCell);
    const points = finiteNumber(bucket?.pts);
    const count = finiteNumber(bucket?.count);
    textCell(row, formatNumber(points), "text-end");
    textCell(row, formatPercent(bucketPercent(bucket, "points_pct", points, totalPoints)), "text-end");
    textCell(row, formatNumber(count, 0), "text-end");
    textCell(row, formatPercent(bucketPercent(bucket, "issue_pct", count, totalCount)), "text-end");
    overall.appendChild(row);
  });
  const totalRow = document.createElement("tr");
  const totalLabel = document.createElement("th");
  totalLabel.scope = "row";
  totalLabel.textContent = "Total";
  totalRow.appendChild(totalLabel);
  textCell(totalRow, formatNumber(totalPoints), "text-end");
  textCell(totalRow, totalPoints !== null && totalPoints > 0 ? "100%" : "—", "text-end");
  textCell(totalRow, formatNumber(totalCount, 0), "text-end");
  textCell(totalRow, totalCount !== null && totalCount > 0 ? "100%" : "—", "text-end");
  overallTotal.appendChild(totalRow);

  const head = byId("workTypeByDeveloperHead");
  head.replaceChildren();
  const headRow = document.createElement("tr");
  ["Developer", "Total", ...types].forEach((label, index) => {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    if (index > 0) cell.className = "text-end";
    headRow.appendChild(cell);
  });
  head.appendChild(headRow);

  const tbody = byId("workTypeByDeveloper");
  tbody.replaceChildren();
  const assignees = Array.isArray(mix.by_assignee) ? mix.by_assignee : [];
  if (!assignees.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = types.length + 2;
    cell.className = "text-muted py-3";
    cell.textContent = "Developer breakdown is unavailable for this sprint.";
    row.appendChild(cell);
    tbody.appendChild(row);
    return;
  }
  assignees.forEach((assignee) => {
    const row = document.createElement("tr");
    textCell(row, assignee.assignee_name || assignee.assignee_eid || "Unassigned", "sv-developer-name");
    const assigneeEntries = Object.entries(assignee.types || {});
    const assigneePoints = finiteNumber(assignee.total_pts) ?? sumBuckets(assigneeEntries, "pts");
    const assigneeCount = finiteNumber(assignee.total_count) ?? sumBuckets(assigneeEntries, "count");
    const assigneeUnestimated = finiteNumber(assignee.unestimated_count) ?? sumBuckets(assigneeEntries, "unestimated_count");
    const sprintPointPct = assigneePoints !== null && totalPoints !== null && totalPoints > 0
      ? (assigneePoints / totalPoints) * 100
      : null;
    appendMatrixCell(row, assigneePoints, assigneeCount, sprintPointPct, assigneeUnestimated, "of sprint points", true);
    types.forEach((type) => {
      const bucket = assignee.types?.[type];
      if (!bucket) {
        appendMatrixCell(row, null, null, null);
      } else {
        const points = finiteNumber(bucket.pts);
        const count = finiteNumber(bucket.count);
        appendMatrixCell(row, points, count, bucketPercent(bucket, "points_pct", points, assigneePoints), bucket.unestimated_count);
      }
    });
    tbody.appendChild(row);
  });
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

export function renderMetrics(metrics) {
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
      : `${formatNumber(count, 0)} issues (${formatNumber(points)} pts)`
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
}

export function setMetricsPending() {
  byId("metricsBox").classList.remove("d-none");
  byId("metricsUnavailableMessage")?.classList.add("d-none");
  ["committedFmt", "completedOriginalFmt", "deliveredFmt", "spilloverFmt", "scopeAddedFmt", "descopeFmt", "scopeNetFmt", "scopePct", "predictabilityPct", "totalDeliveryPct", "scopeChangePct"].forEach((id) => { byId(id).textContent = "…"; });
}
