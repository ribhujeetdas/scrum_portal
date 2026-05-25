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
  const downloadSprintReportBtn = document.getElementById("downloadSprintReportBtn");
  const sprintMetaBox = document.getElementById("sprintMetaBox");
  const statsBox = document.getElementById("statsBox");
  const metricsBox = document.getElementById("metricsBox");
  const workTypeMixBox = document.getElementById("workTypeMixBox");
  const assigneeAccordion = document.getElementById("assigneeAccordion");
  let currentReportData = null;
  let activeFetchToken = 0;

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

  function setReportDownloadReady(ready) {
    if (!downloadSprintReportBtn) return;
    setDisabled(downloadSprintReportBtn, !ready);
  }

  function setFetchButtonMode(mode) {
    fetchIssuesBtn.dataset.mode = mode;
    if (mode === "start-over") {
      fetchIssuesBtn.textContent = "Start Over";
      fetchIssuesBtn.classList.remove("btn-primary");
      fetchIssuesBtn.classList.add("btn-outline-danger");
      return;
    }
    fetchIssuesBtn.textContent = "Fetch Issues";
    fetchIssuesBtn.classList.remove("btn-outline-danger");
    fetchIssuesBtn.classList.add("btn-primary");
  }

  function isStartOverMode() {
    return fetchIssuesBtn.dataset.mode === "start-over";
  }

  function updateControlAvailability() {
    const resultsActive = isStartOverMode();
    setDisabled(boardId, resultsActive || !projectKey.value);
    setDisabled(sprintId, resultsActive || !boardId.value);
    setDisabled(refreshSprintsBtn, resultsActive || !boardId.value);
    setDisabled(fetchIssuesBtn, resultsActive ? false : !sprintId.value);
  }

  function errorMessage(data, fallback) {
    if (!data || !data.error) return fallback;
    if (typeof data.error === "string") return data.error;
    return data.error.message || fallback;
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
    updateControlAvailability();
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
    currentReportData = null;
    setReportDownloadReady(false);
    resultsCard.classList.add("d-none");
    metricsBox.classList.add("d-none");
    statsBox.classList.add("d-none");
    sprintMetaBox.classList.add("d-none");
    workTypeMixBox.classList.add("d-none");
    clear(msgBox);
  }

  function resetPageState() {
    activeFetchToken += 1;
    resetResults();
    setFetchButtonMode("fetch");
    projectKey.value = "";
    boardId.replaceChildren(makeOption("", "-- Select Board --"));
    sprintId.replaceChildren(makeOption("", "-- Select Sprint --"));
    updateControlAvailability();
  }

  function confirmStartOver() {
    if (!window.confirm("Everything displayed for this sprint will be reset. Start over?")) {
      return false;
    }
    resetPageState();
    return true;
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
    return `${safeCount} # (${spText} pts)`;
  }

  function selectedText(select) {
    if (!select || !select.selectedOptions || !select.selectedOptions.length) return "";
    return select.selectedOptions[0].textContent || "";
  }

  function xmlEscape(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&apos;");
  }

  function columnName(index) {
    let name = "";
    let n = index + 1;
    while (n > 0) {
      const rem = (n - 1) % 26;
      name = String.fromCharCode(65 + rem) + name;
      n = Math.floor((n - 1) / 26);
    }
    return name;
  }

  function xlsxCell(value, rowNumber, colIndex) {
    const ref = `${columnName(colIndex)}${rowNumber}`;
    if (typeof value === "number" && Number.isFinite(value)) {
      return `<c r="${ref}"><v>${value}</v></c>`;
    }
    return `<c r="${ref}" t="inlineStr"><is><t>${xmlEscape(value)}</t></is></c>`;
  }

  function worksheetXml(rows) {
    const body = rows.map((row, rowIndex) => {
      const rowNumber = rowIndex + 1;
      return `<row r="${rowNumber}">${(row || []).map((value, colIndex) => xlsxCell(value, rowNumber, colIndex)).join("")}</row>`;
    }).join("");
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>${body}</sheetData></worksheet>`;
  }

  function addKeyValueSection(rows, title, pairs) {
    rows.push([title, "", "", "", "", ""]);
    rows.push(["Section", "Metric", "Count", "Points", "Percent", "Value"]);
    (pairs || []).forEach(([label, value]) => rows.push([title, label, "", "", "", value ?? ""]));
    rows.push([]);
  }

  function buildSprintSummaryRows(report) {
    const issueData = report.issueData || {};
    const metrics = report.metrics || {};
    const stats = issueData.stats || {};
    const sprint = issueData.sprint || {};
    const workTypeMix = issueData.work_type_mix || {};
    const rows = [];

    addKeyValueSection(rows, "Sprint Metadata", [
      ["Project Key", report.projectKey],
      ["Board", report.boardName],
      ["Board ID", report.boardId],
      ["Sprint", sprint.name || report.sprintName],
      ["Sprint ID", report.sprintId],
      ["Planned Start", shortDate(sprint.start_date)],
      ["Actual Start", shortDate(sprint.activated_date)],
      ["Planned End", shortDate(sprint.end_date)],
      ["Actual End", shortDate(sprint.complete_date)],
      ["Goal", sprint.goal || ""],
      ["Historical fallback rows", issueData.historical_fallback_count ?? 0],
    ]);

    addKeyValueSection(rows, "Totals", [
      ["Total issues", issueData.total ?? 0],
      ["Standard issues", issueData.standard_total ?? 0],
      ["Total points", issueData.total_sp ?? 0],
    ]);

    addKeyValueSection(rows, "Quality Metrics", [
      ["Unestimated count", stats.unestimated_count ?? 0],
      ["Unestimated %", stats.unestimated_pct ?? 0],
      ["Bug count", stats.bug_count ?? 0],
      ["Bug %", stats.bug_pct ?? 0],
      ["Bug points", stats.bug_sp ?? 0],
      ["Unassigned count", stats.unassigned_count ?? 0],
      ["Unassigned %", stats.unassigned_pct ?? 0],
      ["No relevant comments count", stats.zero_relevant_comment_count ?? 0],
      ["No relevant comments %", stats.zero_relevant_comment_pct ?? 0],
      ["Relevant comments count", stats.relevant_comment_count ?? 0],
      ["Carryover count", stats.carryover_count ?? 0],
      ["Carryover points", stats.carryover_sp ?? 0],
    ]);

    rows.push(["Scrum Metrics", "Metric", "Count", "Points", "Percent", "Value"]);
    rows.push(["Scrum Metrics", "Original Commitment", metrics.committed_count ?? 0, metrics.committed_sp ?? 0, "", ""]);
    rows.push(["Scrum Metrics", "Completed from Commitment", metrics.completed_original_count ?? 0, metrics.completed_original_sp ?? 0, "", ""]);
    rows.push(["Scrum Metrics", "Total Completed", metrics.delivered_count ?? 0, metrics.delivered_sp ?? 0, "", ""]);
    rows.push(["Scrum Metrics", "Carryover", metrics.spillover_count ?? 0, metrics.spillover_sp ?? 0, "", ""]);
    rows.push(["Scrum Metrics", "Added Scope", metrics.scope_added_count ?? 0, metrics.scope_added_sp ?? 0, metrics.scope_pct ?? 0, ""]);
    rows.push(["Scrum Metrics", "Removed Scope", metrics.descope_count ?? 0, metrics.descope_sp ?? 0, "", ""]);
    rows.push(["Scrum Metrics", "Net Scope Change", metrics.scope_net_count ?? 0, metrics.scope_net_sp ?? 0, "", ""]);
    rows.push(["Scrum Metrics", "Commitment Predictability", "", "", metrics.predictability_pct ?? 0, ""]);
    rows.push(["Scrum Metrics", "Total Delivery vs Commitment", "", "", metrics.total_delivery_vs_commitment_pct ?? 0, ""]);
    rows.push(["Scrum Metrics", "Scope Change", "", "", metrics.scope_change_pct ?? 0, ""]);
    rows.push([]);

    rows.push(["Work Type Mix", "Issue Type", "Count", "Points", "", ""]);
    Object.entries(workTypeMix.overall || {}).forEach(([type, bucket]) => {
      rows.push(["Work Type Mix", type, bucket.count ?? 0, bucket.pts ?? 0, "", ""]);
    });
    rows.push([]);

    rows.push(["Work Type Mix by Developer", "Developer", "", "", "", "Type Mix"]);
    (workTypeMix.by_assignee || []).forEach((row) => {
      const mix = Object.entries(row.types || {})
        .map(([type, bucket]) => `${type}: ${bucket.count ?? 0} #, ${bucket.pts ?? 0} pts`)
        .join("; ");
      rows.push(["Work Type Mix by Developer", row.assignee_name || row.assignee_eid || "Unassigned", "", "", "", mix]);
    });

    return rows;
  }

  function buildTicketDetailRows(report) {
    const groups = (report.issueData && report.issueData.groups) || [];
    const scopeKeys = new Set((report.metrics && report.metrics.scope_added_keys) || []);
    const rows = [[
      "Developer",
      "Developer EID",
      "Issue Key",
      "Summary",
      "Type",
      "Status",
      "Story Points",
      "Feature Key",
      "Relevant Comments",
      "Data",
      "Added After Sprint Start",
    ]];

    groups.forEach((group) => {
      (group.issues || []).forEach((issue) => {
        rows.push([
          group.assignee_name || "Unassigned",
          group.assignee_eid || "",
          issue.issue_key || "",
          issue.summary || "",
          issue.issue_type || "",
          issue.status || "",
          issue.story_points ?? "",
          issue.feature_key || "",
          issue.relevant_comment_count ?? 0,
          issue.historical_fallback ? "Current fallback" : "Sprint-end",
          scopeKeys.has(issue.issue_key) ? "Yes" : "No",
        ]);
      });
    });

    return rows;
  }

  function buildSprintReportWorkbook(report) {
    return {
      sheets: [
        { name: "Sprint Summary", rows: buildSprintSummaryRows(report) },
        { name: "Ticket Details", rows: buildTicketDetailRows(report) },
      ],
    };
  }

  function crc32(bytes) {
    if (!crc32.table) {
      crc32.table = Array.from({ length: 256 }, (_, n) => {
        let c = n;
        for (let k = 0; k < 8; k += 1) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
        return c >>> 0;
      });
    }
    let crc = 0xffffffff;
    bytes.forEach((byte) => {
      crc = crc32.table[(crc ^ byte) & 0xff] ^ (crc >>> 8);
    });
    return (crc ^ 0xffffffff) >>> 0;
  }

  function writeUint16(target, offset, value) {
    target[offset] = value & 0xff;
    target[offset + 1] = (value >>> 8) & 0xff;
  }

  function writeUint32(target, offset, value) {
    target[offset] = value & 0xff;
    target[offset + 1] = (value >>> 8) & 0xff;
    target[offset + 2] = (value >>> 16) & 0xff;
    target[offset + 3] = (value >>> 24) & 0xff;
  }

  function concatBytes(parts) {
    const total = parts.reduce((sum, part) => sum + part.length, 0);
    const out = new Uint8Array(total);
    let offset = 0;
    parts.forEach((part) => {
      out.set(part, offset);
      offset += part.length;
    });
    return out;
  }

  function zipFiles(files) {
    const encoder = new TextEncoder();
    const localParts = [];
    const centralParts = [];
    let offset = 0;

    files.forEach((file) => {
      const nameBytes = encoder.encode(file.name);
      const dataBytes = encoder.encode(file.content);
      const crc = crc32(dataBytes);
      const local = new Uint8Array(30 + nameBytes.length);
      writeUint32(local, 0, 0x04034b50);
      writeUint16(local, 4, 20);
      writeUint16(local, 8, 0);
      writeUint32(local, 14, crc);
      writeUint32(local, 18, dataBytes.length);
      writeUint32(local, 22, dataBytes.length);
      writeUint16(local, 26, nameBytes.length);
      local.set(nameBytes, 30);
      localParts.push(local, dataBytes);

      const central = new Uint8Array(46 + nameBytes.length);
      writeUint32(central, 0, 0x02014b50);
      writeUint16(central, 4, 20);
      writeUint16(central, 6, 20);
      writeUint16(central, 10, 0);
      writeUint32(central, 16, crc);
      writeUint32(central, 20, dataBytes.length);
      writeUint32(central, 24, dataBytes.length);
      writeUint16(central, 28, nameBytes.length);
      writeUint32(central, 42, offset);
      central.set(nameBytes, 46);
      centralParts.push(central);

      offset += local.length + dataBytes.length;
    });

    const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0);
    const end = new Uint8Array(22);
    writeUint32(end, 0, 0x06054b50);
    writeUint16(end, 8, files.length);
    writeUint16(end, 10, files.length);
    writeUint32(end, 12, centralSize);
    writeUint32(end, 16, offset);
    return concatBytes([...localParts, ...centralParts, end]);
  }

  function workbookXml(workbook) {
    const sheets = workbook.sheets.map((sheet, idx) => (
      `<sheet name="${xmlEscape(sheet.name)}" sheetId="${idx + 1}" r:id="rId${idx + 1}"/>`
    )).join("");
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>${sheets}</sheets></workbook>`;
  }

  function workbookRelsXml(workbook) {
    const rels = workbook.sheets.map((_, idx) => (
      `<Relationship Id="rId${idx + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${idx + 1}.xml"/>`
    )).join("");
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${rels}</Relationships>`;
  }

  function contentTypesXml(workbook) {
    const sheets = workbook.sheets.map((_, idx) => (
      `<Override PartName="/xl/worksheets/sheet${idx + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`
    )).join("");
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>${sheets}</Types>`;
  }

  function buildXlsxBlob(workbook) {
    const files = [
      { name: "[Content_Types].xml", content: contentTypesXml(workbook) },
      { name: "_rels/.rels", content: "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/></Relationships>" },
      { name: "xl/workbook.xml", content: workbookXml(workbook) },
      { name: "xl/_rels/workbook.xml.rels", content: workbookRelsXml(workbook) },
      ...workbook.sheets.map((sheet, idx) => ({
        name: `xl/worksheets/sheet${idx + 1}.xml`,
        content: worksheetXml(sheet.rows),
      })),
    ];
    return new Blob([zipFiles(files)], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
  }

  function safeFileName(value) {
    return String(value || "sprint-report")
      .replace(/[^a-z0-9_-]+/gi, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 80) || "sprint-report";
  }

  function downloadSprintReport() {
    if (!currentReportData || !currentReportData.metrics) return;
    const workbook = buildSprintReportWorkbook(currentReportData);
    const blob = buildXlsxBlob(workbook);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const sprintPart = safeFileName(currentReportData.sprintName || currentReportData.sprintId);
    link.href = url;
    link.download = `${sprintPart}-sprint-report.xlsx`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
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
        showAlert("danger", errorMessage(data, "Failed to load sprints."));
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

  function setTotals(totalIssues, totalSp, standardTotal) {
    $("totalIssues").textContent = totalIssues ?? 0;
    $("totalSp").textContent = typeof totalSp === "number" ? totalSp.toFixed(2) : (totalSp ?? 0);
    $("standardTotal").textContent = standardTotal ?? 0;
  }

  function shortDate(value) {
    if (!value) return "-";
    return String(value).replace("T", " ").slice(0, 19);
  }

  function renderSprintMeta(sprint, fallbackCount) {
    if (!sprint) {
      sprintMetaBox.classList.add("d-none");
      return;
    }
    sprintMetaBox.classList.remove("d-none");
    $("sprintName").textContent = sprint.name || sprint.id || "-";
    $("sprintStartDate").textContent = shortDate(sprint.start_date);
    $("sprintActualStartDate").textContent = shortDate(sprint.activated_date);
    $("sprintEndDate").textContent = shortDate(sprint.end_date);
    $("sprintActualEndDate").textContent = shortDate(sprint.complete_date);
    $("sprintGoal").textContent = sprint.goal || "-";
    const note = $("historicalFallbackNote");
    if ((fallbackCount || 0) > 0) {
      note.classList.remove("d-none");
      note.textContent = `${fallbackCount} row(s) use current Jira values because sprint-end changelog data was unavailable.`;
    } else {
      note.classList.add("d-none");
    }
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
    $("zeroRelevantCommentCount").textContent = stats.zero_relevant_comment_count ?? 0;
    $("zeroRelevantCommentPct").textContent = stats.zero_relevant_comment_pct ?? 0;
    $("relevantCommentCount").textContent = stats.relevant_comment_count ?? 0;
    $("carryoverCount").textContent = stats.carryover_count ?? 0;
    $("carryoverPts").textContent = stats.carryover_sp ?? 0;
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
      addText(button, `${group.issue_count ?? 0} issues, ${typeof spSum === "number" ? spSum.toFixed(2) : spSum} pts, ${group.relevant_comment_count ?? 0} relevant comments`, "ms-2 text-muted");
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
      ["Key", "Summary", "Type", "Status", "Pts", "Feature Key", "Relevant Comments", "Data"].forEach((label) => {
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
        addCell(row, issue.relevant_comment_count ?? 0);
        addCell(row, issue.historical_fallback ? "Current fallback" : "Sprint-end");
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
      "completedOriginalFmt", "scopeNetFmt", "scopePct", "predictabilityPct",
      "totalDeliveryPct", "scopeChangePct"
    ].forEach((id) => {
      $(id).textContent = "...";
    });
    $("scopePct").style.color = "";
  }

  function renderMetrics(metrics) {
    if (!metrics) {
      metricsBox.classList.add("d-none");
      return;
    }
    metricsBox.classList.remove("d-none");
    $("committedFmt").textContent = fmtCountSp(metrics.committed_count, metrics.committed_sp);
    $("completedOriginalFmt").textContent = fmtCountSp(metrics.completed_original_count, metrics.completed_original_sp);
    $("deliveredFmt").textContent = fmtCountSp(metrics.delivered_count, metrics.delivered_sp);
    $("spilloverFmt").textContent = fmtCountSp(metrics.spillover_count, metrics.spillover_sp);
    $("scopeAddedFmt").textContent = fmtCountSp(metrics.scope_added_count, metrics.scope_added_sp);
    $("descopeFmt").textContent = fmtCountSp(metrics.descope_count, metrics.descope_sp);
    $("scopeNetFmt").textContent = fmtCountSp(metrics.scope_net_count, metrics.scope_net_sp);
    $("scopePct").textContent = metrics.scope_pct ?? 0;
    $("predictabilityPct").textContent = metrics.predictability_pct ?? 0;
    $("totalDeliveryPct").textContent = metrics.total_delivery_vs_commitment_pct ?? 0;
    $("scopeChangePct").textContent = metrics.scope_change_pct ?? 0;
    $("scopePct").style.color = metrics.scope_red ? "red" : "";
  }

  function renderWorkTypeMix(workTypeMix) {
    if (!workTypeMix) {
      workTypeMixBox.classList.add("d-none");
      return;
    }
    workTypeMixBox.classList.remove("d-none");
    const overall = $("workTypeOverall");
    overall.replaceChildren();
    Object.entries(workTypeMix.overall || {}).forEach(([type, bucket]) => {
      const item = document.createElement("div");
      item.className = "sv-stat";
      const label = document.createElement("strong");
      label.textContent = `${type}: `;
      item.appendChild(label);
      addText(item, `${bucket.count ?? 0} #, ${bucket.pts ?? 0} pts`);
      overall.appendChild(item);
    });

    const tbody = $("workTypeByDeveloper");
    tbody.replaceChildren();
    (workTypeMix.by_assignee || []).forEach((row) => {
      const tr = document.createElement("tr");
      addCell(tr, row.assignee_name || row.assignee_eid || "Unassigned");
      const mix = Object.entries(row.types || {})
        .map(([type, bucket]) => `${type}: ${bucket.count ?? 0} #, ${bucket.pts ?? 0} pts`)
        .join("; ");
      addCell(tr, mix);
      tbody.appendChild(tr);
    });
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

  async function startMetricsRequest(bid, sid) {
    try {
      return await postJson("/api/automation/sprint-viewer/metrics", {
        board_id: bid,
        sprint_id: sid,
        total_sp: 0,
        total_count: 0
      });
    } catch (error) {
      return { ok: false, error: "Network/Unexpected error while calculating metrics." };
    }
  }

  function renderMetricsResult(data, bid, sid) {
    if (!data || !data.ok) {
      showAlert("warning", `Issues loaded. Metrics failed: ${errorMessage(data, "Unknown error")}`);
      metricsBox.classList.add("d-none");
      setReportDownloadReady(false);
      return false;
    }
    renderMetrics(data.metrics);
    applyScopeStars(data.metrics && data.metrics.scope_added_keys ? data.metrics.scope_added_keys : []);
    if (currentReportData && currentReportData.boardId === bid && currentReportData.sprintId === sid) {
      currentReportData.metrics = data.metrics || {};
      setReportDownloadReady(true);
    }
    return true;
  }

  projectKey.addEventListener("change", () => {
    const selectedProject = (projectKey.value || "").trim().toUpperCase();
    projectKey.value = selectedProject;
    resetResults();
    setFetchButtonMode("fetch");
    populateBoards(selectedProject);
    sprintId.replaceChildren(makeOption("", "-- Select Sprint --"));
    updateControlAvailability();
  });

  boardId.addEventListener("change", () => {
    resetResults();
    if (!boardId.value) {
      updateControlAvailability();
      return;
    }
    updateControlAvailability();
    loadSprints(false);
  });

  refreshSprintsBtn.addEventListener("click", () => {
    resetResults();
    loadSprints(true);
  });

  sprintId.addEventListener("change", () => {
    resetResults();
    updateControlAvailability();
  });

  fetchIssuesBtn.addEventListener("click", async () => {
    if (isStartOverMode()) {
      confirmStartOver();
      return;
    }
    const bid = Number(boardId.value);
    const sid = Number(sprintId.value);
    const fetchToken = activeFetchToken + 1;
    activeFetchToken = fetchToken;
    resetResults();
    setFetchButtonMode("start-over");
    lockUi();
    const metricsPromise = startMetricsRequest(bid, sid);
    try {
      const data = await postJson("/api/automation/sprint-viewer/issues", {
        board_id: bid,
        sprint_id: sid
      });
      if (fetchToken !== activeFetchToken) return;
      if (!data.ok) {
        showAlert("danger", errorMessage(data, "Failed to fetch sprint issues."));
        setFetchButtonMode("fetch");
        return;
      }
      currentReportData = {
        projectKey: projectKey.value.trim().toUpperCase(),
        boardId: bid,
        boardName: selectedText(boardId),
        sprintId: sid,
        sprintName: selectedText(sprintId),
        issueData: data,
        metrics: null,
      };
      setReportDownloadReady(false);
      setTotals(data.total, data.total_sp, data.standard_total);
      renderSprintMeta(data.sprint, data.historical_fallback_count);
      renderStats(data.stats);
      renderWorkTypeMix(data.work_type_mix);
      renderGroupedAccordion(data.groups || []);
      resultsCard.classList.remove("d-none");
      showAlert("success", "Issues fetched successfully. Metrics are calculating...");
      showMetricsLoading();
      const metricsData = await metricsPromise;
      if (fetchToken !== activeFetchToken) return;
      renderMetricsResult(metricsData, bid, sid);
    } catch (error) {
      showAlert("danger", "Network/Unexpected error while fetching sprint issues.");
      setFetchButtonMode("fetch");
    } finally {
      unlockUi();
    }
  });

  if (downloadSprintReportBtn) {
    downloadSprintReportBtn.addEventListener("click", downloadSprintReport);
  }
})();
