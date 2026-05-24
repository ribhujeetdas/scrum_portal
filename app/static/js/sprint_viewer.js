(function () {
  const page = document.getElementById("sprintViewerPage");
  if (!page) return;

  const boardsByProject = JSON.parse(page.getAttribute("data-boards") || "{}");
  const jiraBaseUrl = page.getAttribute("data-jira-base-url") || "";
  const apiFetch = window.portalApiFetch || window.fetch.bind(window);
  const overlay = document.getElementById("loadingOverlay");
  const projectKey = document.getElementById("projectKey");
  const boardId = document.getElementById("boardId");
  const sprintId = document.getElementById("sprintId");
  const refreshSprintsBtn = document.getElementById("refreshSprintsBtn");
  const fetchIssuesBtn = document.getElementById("fetchIssuesBtn");
  const msgBox = document.getElementById("msgBox");
  const resultsCard = document.getElementById("resultsCard");
  const statsBox = document.getElementById("statsBox");
  const metricsBox = document.getElementById("metricsBox");
  const assigneeAccordion = document.getElementById("assigneeAccordion");

  function $(id) {
    return document.getElementById(id);
  }

  function setDisabled(el, disabled) {
    if (disabled) el.setAttribute("disabled", "disabled");
    else el.removeAttribute("disabled");
  }

  function clear(el) {
    if (el) el.replaceChildren();
  }

  function makeOption(value, text) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    return option;
  }

  function lockUi() {
    if (overlay) overlay.style.display = "flex";
    page.querySelectorAll("button, input, select, textarea, a").forEach((el) => {
      el.dataset.prevDisabled = el.hasAttribute("disabled") ? "1" : "0";
      el.dataset.prevPointer = el.style.pointerEvents || "";
      el.setAttribute("disabled", "disabled");
      el.style.pointerEvents = "none";
    });
  }

  function unlockUi() {
    if (overlay) overlay.style.display = "none";
    page.querySelectorAll("button, input, select, textarea, a").forEach((el) => {
      if (el.dataset.prevDisabled === "1") el.setAttribute("disabled", "disabled");
      else el.removeAttribute("disabled");
      el.style.pointerEvents = el.dataset.prevPointer || "";
      delete el.dataset.prevDisabled;
      delete el.dataset.prevPointer;
    });
    setDisabled(boardId, !projectKey.value);
    setDisabled(sprintId, !boardId.value);
    setDisabled(refreshSprintsBtn, !boardId.value);
    setDisabled(fetchIssuesBtn, !sprintId.value);
  }

  function showAlert(kind, text) {
    if (window.portalShowToast) {
      window.portalShowToast(text, kind);
      clear(msgBox);
      return;
    }
    const safeKind = ["success", "danger", "warning", "info"].includes(kind) ? kind : "info";
    const alert = document.createElement("div");
    alert.className = `alert alert-${safeKind} mb-0`;
    alert.textContent = text;
    msgBox.replaceChildren(alert);
  }

  async function postJson(url, payload) {
    const response = await apiFetch(url, {
      method: "POST",
      body: JSON.stringify(payload || {})
    });
    return response.json();
  }

  function resetResults() {
    resultsCard.classList.add("d-none");
    metricsBox.classList.add("d-none");
    statsBox.classList.add("d-none");
    clear(msgBox);
  }

  function populateBoards(project) {
    boardId.replaceChildren(makeOption("", "-- Select Board --"));
    (boardsByProject[project] || []).forEach((board) => {
      boardId.appendChild(makeOption(board.board_id, `${board.board_name} (ID: ${board.board_id})`));
    });
  }

  function populateSprints(sprints) {
    sprintId.replaceChildren(makeOption("", "-- Select Sprint --"));
    (sprints || []).forEach((sprint) => {
      sprintId.appendChild(makeOption(sprint.id, `${sprint.name} (ID: ${sprint.id})`));
    });
  }

  function fmtCountSp(count, sp) {
    const safeCount = count ?? 0;
    const safeSp = sp ?? 0;
    const spText = typeof safeSp === "number" ? safeSp.toFixed(2) : safeSp;
    return `${safeCount} (${spText} SP)`;
  }

  async function loadSprints(refresh) {
    lockUi();
    try {
      const data = await postJson("/api/automation/sprint-viewer/sprints", {
        project_key: projectKey.value.trim().toUpperCase(),
        board_id: Number(boardId.value),
        refresh: Boolean(refresh)
      });
      if (!data.ok) {
        showAlert("danger", data.error || "Failed to load sprints.");
        return;
      }
      populateSprints(data.sprints || []);
      setDisabled(sprintId, false);
      showAlert("success", `Sprints loaded (${data.source}). Select a sprint to fetch issues.`);
    } catch (error) {
      showAlert("danger", "Network/Unexpected error while loading sprints.");
    } finally {
      unlockUi();
    }
  }

  function setTotals(totalIssues, totalSp) {
    $("totalIssues").textContent = totalIssues ?? 0;
    $("totalSp").textContent = typeof totalSp === "number" ? totalSp.toFixed(2) : (totalSp ?? 0);
  }

  function renderStats(stats) {
    if (!stats) {
      statsBox.classList.add("d-none");
      return;
    }
    statsBox.classList.remove("d-none");
    $("unestimatedCount").textContent = stats.unestimated_count ?? 0;
    $("unestimatedPct").textContent = stats.unestimated_pct ?? 0;
    $("bugCount").textContent = stats.bug_count ?? 0;
    $("bugPct").textContent = stats.bug_pct ?? 0;
    $("bugSp").textContent = stats.bug_sp ?? 0;
    $("unassignedCount").textContent = stats.unassigned_count ?? 0;
    $("unassignedPct").textContent = stats.unassigned_pct ?? 0;
    $("zeroCommentCount").textContent = stats.zero_comment_count ?? 0;
    $("zeroCommentPct").textContent = stats.zero_comment_pct ?? 0;
  }

  function addText(parent, text, className) {
    const node = document.createElement("span");
    if (className) node.className = className;
    node.textContent = text;
    parent.appendChild(node);
    return node;
  }

  function addCell(row, text, className) {
    const cell = document.createElement("td");
    if (className) cell.className = className;
    cell.textContent = text ?? "";
    row.appendChild(cell);
    return cell;
  }

  function makeIssueLink(issueKey) {
    const link = document.createElement("a");
    link.href = jiraBaseUrl && issueKey ? `${jiraBaseUrl}/browse/${encodeURIComponent(issueKey)}` : "#";
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = issueKey;
    return link;
  }

  function renderGroupedAccordion(groups) {
    assigneeAccordion.replaceChildren();
    (groups || []).forEach((group, idx) => {
      const headerId = `heading_${idx}`;
      const collapseId = `collapse_${idx}`;
      const item = document.createElement("div");
      item.className = "accordion-item";

      const header = document.createElement("h2");
      header.className = "accordion-header";
      header.id = headerId;
      const button = document.createElement("button");
      button.className = "accordion-button collapsed";
      button.type = "button";
      button.setAttribute("data-bs-toggle", "collapse");
      button.setAttribute("data-bs-target", `#${collapseId}`);
      button.setAttribute("aria-expanded", "false");
      button.setAttribute("aria-controls", collapseId);
      addText(button, group.assignee_name || "Unassigned");
      const spSum = group.sp_sum ?? 0;
      addText(button, `${group.issue_count ?? 0} issues, ${typeof spSum === "number" ? spSum.toFixed(2) : spSum} SP`, "ms-2 text-muted");
      header.appendChild(button);

      const collapse = document.createElement("div");
      collapse.id = collapseId;
      collapse.className = "accordion-collapse collapse";
      collapse.setAttribute("aria-labelledby", headerId);
      collapse.setAttribute("data-bs-parent", "#assigneeAccordion");
      const body = document.createElement("div");
      body.className = "accordion-body";
      const eid = document.createElement("div");
      eid.className = "mb-2 text-muted small";
      eid.textContent = `EID: ${group.assignee_eid || ""}`;
      body.appendChild(eid);

      const tableWrap = document.createElement("div");
      tableWrap.className = "table-responsive";
      const table = document.createElement("table");
      table.className = "table table-sm table-striped align-middle";
      const thead = document.createElement("thead");
      const headRow = document.createElement("tr");
      ["Key", "Summary", "Type", "Status", "SP", "Feature Key", "Comments"].forEach((label) => {
        const th = document.createElement("th");
        th.textContent = label;
        if (label === "Key" || label === "Feature Key") th.className = label === "Key" ? "col-key nowrap" : "col-feature nowrap";
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);
      table.appendChild(thead);

      const tbody = document.createElement("tbody");
      (group.issues || []).forEach((issue) => {
        const row = document.createElement("tr");
        const keyCell = document.createElement("td");
        keyCell.className = "col-key nowrap";
        if (issue.issue_key) {
          keyCell.appendChild(makeIssueLink(issue.issue_key));
          const star = document.createElement("span");
          star.className = "scope-star";
          star.setAttribute("data-issue-key", issue.issue_key);
          keyCell.appendChild(star);
        }
        row.appendChild(keyCell);
        addCell(row, issue.summary || "");
        addCell(row, issue.issue_type || "");
        addCell(row, issue.status || "");
        addCell(row, issue.story_points ?? "");
        const featureCell = document.createElement("td");
        featureCell.className = "col-feature nowrap";
        if (issue.feature_key) featureCell.appendChild(makeIssueLink(issue.feature_key));
        row.appendChild(featureCell);
        addCell(row, issue.comment_total ?? 0);
        tbody.appendChild(row);
      });
      table.appendChild(tbody);
      tableWrap.appendChild(table);
      body.appendChild(tableWrap);
      collapse.appendChild(body);
      item.appendChild(header);
      item.appendChild(collapse);
      assigneeAccordion.appendChild(item);
    });
  }

  function showMetricsLoading() {
    metricsBox.classList.remove("d-none");
    [
      "committedFmt", "deliveredFmt", "spilloverFmt", "scopeAddedFmt", "descopeFmt",
      "spillPct", "scopePct", "predictabilityPct", "completionSpPct", "completionCountPct",
      "unplannedSpPct", "unplannedCountPct", "scopeChurnSpPct", "scopeChurnCountPct"
    ].forEach((id) => {
      $(id).textContent = "...";
    });
    $("spillPct").style.color = "";
    $("scopePct").style.color = "";
  }

  function renderMetrics(metrics) {
    if (!metrics) {
      metricsBox.classList.add("d-none");
      return;
    }
    metricsBox.classList.remove("d-none");
    $("committedFmt").textContent = fmtCountSp(metrics.committed_count, metrics.committed_sp);
    $("deliveredFmt").textContent = fmtCountSp(metrics.delivered_count, metrics.delivered_sp);
    $("spilloverFmt").textContent = fmtCountSp(metrics.spillover_count, metrics.spillover_sp);
    $("scopeAddedFmt").textContent = fmtCountSp(metrics.scope_added_count, metrics.scope_added_sp);
    $("descopeFmt").textContent = fmtCountSp(metrics.descope_count, metrics.descope_sp);
    $("spillPct").textContent = metrics.spill_pct ?? 0;
    $("scopePct").textContent = metrics.scope_pct ?? 0;
    $("predictabilityPct").textContent = metrics.predictability_pct ?? 0;
    $("completionSpPct").textContent = metrics.completion_sp_pct ?? 0;
    $("completionCountPct").textContent = metrics.completion_count_pct ?? 0;
    $("unplannedSpPct").textContent = metrics.unplanned_sp_pct ?? 0;
    $("unplannedCountPct").textContent = metrics.unplanned_count_pct ?? 0;
    $("scopeChurnSpPct").textContent = metrics.scope_churn_sp_pct ?? 0;
    $("scopeChurnCountPct").textContent = metrics.scope_churn_count_pct ?? 0;
    $("spillPct").style.color = metrics.spill_red ? "red" : "";
    $("scopePct").style.color = metrics.scope_red ? "red" : "";
  }

  function applyScopeStars(scopeKeys) {
    const keys = new Set(scopeKeys || []);
    document.querySelectorAll(".scope-star").forEach((el) => {
      const issueKey = el.getAttribute("data-issue-key");
      el.textContent = keys.has(issueKey) ? "*" : "";
      if (keys.has(issueKey)) el.title = "Added after sprint start";
      else el.removeAttribute("title");
    });
  }

  async function fetchMetricsAsync(bid, sid, totalSp, totalCount) {
    try {
      const data = await postJson("/api/automation/sprint-viewer/metrics", {
        board_id: bid,
        sprint_id: sid,
        total_sp: totalSp,
        total_count: totalCount
      });
      if (!data.ok) {
        showAlert("warning", `Issues loaded. Metrics failed: ${data.error || "Unknown error"}`);
        metricsBox.classList.add("d-none");
        return;
      }
      renderMetrics(data.metrics);
      applyScopeStars(data.metrics && data.metrics.scope_added_keys ? data.metrics.scope_added_keys : []);
    } catch (error) {
      showAlert("warning", "Issues loaded. Metrics failed due to network/unexpected error.");
      metricsBox.classList.add("d-none");
    }
  }

  projectKey.addEventListener("change", () => {
    const selectedProject = (projectKey.value || "").trim().toUpperCase();
    projectKey.value = selectedProject;
    resetResults();
    populateBoards(selectedProject);
    setDisabled(boardId, false);
    sprintId.replaceChildren(makeOption("", "-- Select Sprint --"));
    setDisabled(sprintId, true);
    setDisabled(refreshSprintsBtn, true);
    setDisabled(fetchIssuesBtn, true);
  });

  boardId.addEventListener("change", () => {
    resetResults();
    if (!boardId.value) {
      setDisabled(sprintId, true);
      setDisabled(refreshSprintsBtn, true);
      setDisabled(fetchIssuesBtn, true);
      return;
    }
    setDisabled(refreshSprintsBtn, false);
    loadSprints(false);
  });

  refreshSprintsBtn.addEventListener("click", () => {
    resetResults();
    loadSprints(true);
  });

  sprintId.addEventListener("change", () => {
    resultsCard.classList.add("d-none");
    metricsBox.classList.add("d-none");
    statsBox.classList.add("d-none");
    setDisabled(fetchIssuesBtn, !sprintId.value);
  });

  fetchIssuesBtn.addEventListener("click", async () => {
    const bid = Number(boardId.value);
    const sid = Number(sprintId.value);
    resetResults();
    lockUi();
    try {
      const data = await postJson("/api/automation/sprint-viewer/issues", {
        board_id: bid,
        sprint_id: sid
      });
      if (!data.ok) {
        showAlert("danger", data.error || "Failed to fetch sprint issues.");
        return;
      }
      setTotals(data.total, data.total_sp);
      renderStats(data.stats);
      renderGroupedAccordion(data.groups || []);
      resultsCard.classList.remove("d-none");
      showAlert("success", "Issues fetched successfully. Metrics are calculating...");
      showMetricsLoading();
      fetchMetricsAsync(bid, sid, data.total_sp, data.total);
    } catch (error) {
      showAlert("danger", "Network/Unexpected error while fetching sprint issues.");
    } finally {
      unlockUi();
    }
  });
})();
