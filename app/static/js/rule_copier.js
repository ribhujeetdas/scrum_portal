(function () {
  const page = document.getElementById("ruleCopierPage");
  if (!page) return;

  const boardsByProject = JSON.parse(page.getAttribute("data-boards") || "{}");
  const apiFetch = window.portalApiFetch || window.fetch.bind(window);
  const overlay = document.getElementById("loadingOverlay");
  const srcProject = document.getElementById("srcProject");
  const srcBoard = document.getElementById("srcBoard");
  const ruleSearch = document.getElementById("ruleSearch");
  const sourceRule = document.getElementById("sourceRule");
  const refreshRulesBtn = document.getElementById("refreshRulesBtn");
  const ruleListStatus = document.getElementById("ruleListStatus");
  const fetchRuleBtn = document.getElementById("fetchRuleBtn");
  const confirmBtn = document.getElementById("confirmBtn");
  const confirmSection = document.getElementById("confirmSection");
  const fetchMsg = document.getElementById("fetchMsg");
  const ruleDetailsCard = document.getElementById("ruleDetailsCard");
  const outRuleId = document.getElementById("outRuleId");
  const outRuleName = document.getElementById("outRuleName");
  const outRuleState = document.getElementById("outRuleState");
  const step2 = document.getElementById("step2");
  const dstProject = document.getElementById("dstProject");
  const dstBoard = document.getElementById("dstBoard");
  const copyRuleBtn = document.getElementById("copyRuleBtn");
  const copyMsg = document.getElementById("copyMsg");

  let sourceRules = [];
  let rulesLoading = false;
  let rulesRequestVersion = 0;
  let fetchedRuleId = null;
  let fetchedRuleJson = null;
  let fetchCompleted = false;
  let confirmCompleted = false;

  function clear(el) {
    if (el) el.replaceChildren();
  }

  function setDisabled(el, disabled) {
    if (!el) return;
    if (disabled) el.setAttribute("disabled", "disabled");
    else el.removeAttribute("disabled");
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
    applyUiState();
  }

  function setFetchEnabled() {
    const ready = Boolean(srcProject.value && srcBoard.value && sourceRule.value);
    setDisabled(fetchRuleBtn, fetchCompleted || rulesLoading || !ready);
  }

  function setCopyEnabled() {
    setDisabled(copyRuleBtn, !(fetchedRuleId && dstProject.value && dstBoard.value));
  }

  function applyUiState() {
    const sourceChosen = Boolean(srcProject.value && srcBoard.value);
    const hasRules = sourceRules.length > 0;
    setDisabled(srcBoard, !srcProject.value);
    setDisabled(ruleSearch, rulesLoading || !hasRules);
    setDisabled(sourceRule, rulesLoading || !hasRules);
    setDisabled(refreshRulesBtn, rulesLoading || !sourceChosen);
    setDisabled(dstBoard, !dstProject.value);
    setFetchEnabled();
    confirmSection.classList.toggle("d-none", !fetchCompleted);
    setDisabled(confirmBtn, !(fetchCompleted && !confirmCompleted));
    setCopyEnabled();
  }

  function makeOption(value, text) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = text;
    return option;
  }

  function populateBoards(selectEl, projectKey) {
    selectEl.replaceChildren(makeOption("", "-- Select Board --"));
    (boardsByProject[projectKey] || []).forEach((board) => {
      selectEl.appendChild(makeOption(board.board_id, `${board.board_name} (ID: ${board.board_id})`));
    });
  }

  function showAlert(container, kind, text) {
    if (window.portalShowToast) {
      window.portalShowToast(text, kind);
      clear(container);
      return;
    }
    const safeKind = ["success", "danger", "warning", "info"].includes(kind) ? kind : "info";
    const alert = document.createElement("div");
    alert.className = `alert alert-${safeKind} mb-0`;
    alert.textContent = text;
    container.replaceChildren(alert);
  }

  function errorMessage(data, fallback) {
    if (typeof data?.error === "string" && data.error) return data.error;
    if (data?.error && typeof data.error.message === "string" && data.error.message) {
      return data.error.message;
    }
    return fallback;
  }

  async function postJson(url, payload) {
    const response = await apiFetch(url, {
      method: "POST",
      body: JSON.stringify(payload)
    });
    return response.json();
  }

  function resetFetchedRule() {
    fetchedRuleId = null;
    fetchedRuleJson = null;
    fetchCompleted = false;
    confirmCompleted = false;
    ruleDetailsCard.classList.add("d-none");
    confirmSection.classList.add("d-none");
    step2.classList.add("d-none");
    setDisabled(copyRuleBtn, true);
  }

  function setRuleListStatus(text, kind) {
    ruleListStatus.textContent = text;
    ruleListStatus.classList.remove("text-danger", "text-success", "text-muted");
    if (kind === "danger") ruleListStatus.classList.add("text-danger");
    else if (kind === "success") ruleListStatus.classList.add("text-success");
    else ruleListStatus.classList.add("text-muted");
  }

  function ruleLabel(rule) {
    const state = rule.state ? ` (${rule.state})` : "";
    return `${rule.id} — ${rule.name}${state}`;
  }

  function renderRuleOptions(preferredRuleId) {
    const query = (ruleSearch.value || "").trim().toLocaleLowerCase();
    const selectedId = String(preferredRuleId || sourceRule.value || "");
    const matchingRules = sourceRules.filter((rule) => {
      if (!query) return true;
      return String(rule.id).toLocaleLowerCase().includes(query)
        || String(rule.name || "").toLocaleLowerCase().includes(query);
    });

    sourceRule.replaceChildren();
    if (!sourceRules.length) {
      sourceRule.appendChild(makeOption("", "-- No automation rules found --"));
      setRuleListStatus("No automation rules were found for this Jira project.", "muted");
      applyUiState();
      return;
    }
    if (!matchingRules.length) {
      sourceRule.appendChild(makeOption("", "-- No matching rules --"));
      setRuleListStatus(`No matches within ${sourceRules.length} loaded rules.`, "muted");
      applyUiState();
      return;
    }

    sourceRule.appendChild(makeOption("", "-- Select Automation Rule --"));
    matchingRules.forEach((rule) => {
      sourceRule.appendChild(makeOption(String(rule.id), ruleLabel(rule)));
    });
    if (matchingRules.some((rule) => String(rule.id) === selectedId)) {
      sourceRule.value = selectedId;
    }
    const shown = matchingRules.length === sourceRules.length
      ? `${sourceRules.length} automation rule${sourceRules.length === 1 ? "" : "s"} loaded from Jira Data Center.`
      : `${matchingRules.length} of ${sourceRules.length} automation rules match your search.`;
    setRuleListStatus(shown, "success");
    applyUiState();
  }

  function clearRuleList(message) {
    rulesRequestVersion += 1;
    sourceRules = [];
    rulesLoading = false;
    ruleSearch.value = "";
    sourceRule.replaceChildren(makeOption("", "-- Select source project and board --"));
    setRuleListStatus(message || "Rules load automatically after a source board is selected.", "muted");
    resetFetchedRule();
    applyUiState();
  }

  async function loadRules() {
    if (!srcProject.value || !srcBoard.value) {
      clearRuleList();
      return;
    }

    const requestVersion = ++rulesRequestVersion;
    const previouslySelected = sourceRule.value;
    rulesLoading = true;
    sourceRules = [];
    ruleSearch.value = "";
    sourceRule.replaceChildren(makeOption("", "Loading automation rules…"));
    setRuleListStatus("Loading automation rules from Jira Data Center…", "muted");
    resetFetchedRule();
    clear(fetchMsg);
    clear(copyMsg);
    applyUiState();

    try {
      const data = await postJson("/api/automation/rule-copier/rules", {
        project_key: srcProject.value.trim().toUpperCase(),
        board_id: Number(srcBoard.value)
      });
      if (requestVersion !== rulesRequestVersion) return;
      if (!data.ok) {
        sourceRule.replaceChildren(makeOption("", "-- Unable to load rules --"));
        setRuleListStatus(errorMessage(data, "Unable to load Jira automation rules."), "danger");
        return;
      }

      sourceRules = Array.isArray(data.rules) ? data.rules : [];
      renderRuleOptions(previouslySelected);
    } catch (_error) {
      if (requestVersion !== rulesRequestVersion) return;
      sourceRule.replaceChildren(makeOption("", "-- Unable to load rules --"));
      setRuleListStatus("Network error while loading Jira automation rules. Select Refresh rules to retry.", "danger");
    } finally {
      if (requestVersion === rulesRequestVersion) {
        rulesLoading = false;
        applyUiState();
      }
    }
  }

  srcProject.addEventListener("change", () => {
    const projectKey = (srcProject.value || "").trim().toUpperCase();
    srcProject.value = projectKey;
    populateBoards(srcBoard, projectKey);
    clearRuleList();
  });

  srcBoard.addEventListener("change", loadRules);
  refreshRulesBtn.addEventListener("click", loadRules);
  ruleSearch.addEventListener("input", () => {
    const selectedBeforeFilter = sourceRule.value;
    renderRuleOptions(selectedBeforeFilter);
    if (sourceRule.value !== selectedBeforeFilter) resetFetchedRule();
    setFetchEnabled();
  });
  sourceRule.addEventListener("change", () => {
    resetFetchedRule();
    clear(fetchMsg);
    clear(copyMsg);
    applyUiState();
  });

  fetchRuleBtn.addEventListener("click", async () => {
    clear(fetchMsg);
    clear(copyMsg);
    resetFetchedRule();

    lockUi();
    try {
      const data = await postJson("/api/automation/rule-copier/fetch", {
        project_key: srcProject.value.trim().toUpperCase(),
        board_id: Number(srcBoard.value),
        rule_id: sourceRule.value
      });
      if (!data.ok) {
        showAlert(fetchMsg, "danger", errorMessage(data, "Failed to fetch rule."));
        return;
      }

      outRuleId.textContent = data.rule.id;
      outRuleName.textContent = data.rule.name;
      outRuleState.textContent = data.rule.state;
      fetchedRuleId = data.rule.id;
      fetchedRuleJson = data.rule_json;
      ruleDetailsCard.classList.remove("d-none");
      showAlert(fetchMsg, "success", "Rule fetched successfully. Click Confirm Details to continue.");
      fetchCompleted = true;
      confirmCompleted = false;
    } catch (_error) {
      showAlert(fetchMsg, "danger", "Network/Unexpected error while fetching rule.");
    } finally {
      unlockUi();
    }
  });

  confirmBtn.addEventListener("click", () => {
    step2.classList.remove("d-none");
    showAlert(copyMsg, "info", "Select destination project and board, then click Copy Rule.");
    confirmCompleted = true;
    applyUiState();
  });

  dstProject.addEventListener("change", () => {
    const projectKey = (dstProject.value || "").trim().toUpperCase();
    dstProject.value = projectKey;
    populateBoards(dstBoard, projectKey);
    setCopyEnabled();
  });
  dstBoard.addEventListener("change", setCopyEnabled);

  copyRuleBtn.addEventListener("click", async () => {
    clear(copyMsg);
    lockUi();
    try {
      const data = await postJson("/api/automation/rule-copier/copy", {
        target_project_key: dstProject.value.trim().toUpperCase(),
        target_board_id: Number(dstBoard.value),
        rule_json: fetchedRuleJson,
        client_action_id: crypto.randomUUID()
      });
      if (!data.ok) {
        showAlert(copyMsg, "danger", errorMessage(data, "Copy failed."));
        return;
      }
      showAlert(copyMsg, "success", data.message || "Rule copied.");
    } catch (_error) {
      showAlert(copyMsg, "danger", "Network/Unexpected error while copying rule.");
    } finally {
      unlockUi();
    }
  });

  applyUiState();
})();
