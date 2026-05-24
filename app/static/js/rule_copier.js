(function () {
  const page = document.getElementById("ruleCopierPage");
  if (!page) return;

  const boardsByProject = JSON.parse(page.getAttribute("data-boards") || "{}");
  const apiFetch = window.portalApiFetch || window.fetch.bind(window);
  const overlay = document.getElementById("loadingOverlay");
  const srcProject = document.getElementById("srcProject");
  const srcBoard = document.getElementById("srcBoard");
  const ruleId = document.getElementById("ruleId");
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
    if (fetchCompleted) {
      setDisabled(fetchRuleBtn, true);
      return;
    }
    const ok = Boolean(srcProject.value && srcBoard.value && /^[0-9]+$/.test((ruleId.value || "").trim()));
    setDisabled(fetchRuleBtn, !ok);
  }

  function setCopyEnabled() {
    setDisabled(copyRuleBtn, !(fetchedRuleId && dstProject.value && dstBoard.value));
  }

  function applyUiState() {
    setDisabled(srcBoard, !srcProject.value);
    setDisabled(dstBoard, !dstProject.value);
    setFetchEnabled();
    confirmSection.classList.toggle("d-none", !fetchCompleted);
    setDisabled(confirmBtn, !(fetchCompleted && !confirmCompleted));
    if (confirmCompleted) setDisabled(confirmBtn, true);
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

  async function postJson(url, payload) {
    const response = await apiFetch(url, {
      method: "POST",
      body: JSON.stringify(payload)
    });
    return response.json();
  }

  ruleId.addEventListener("input", () => {
    ruleId.value = (ruleId.value || "").replace(/[^0-9]/g, "");
    setFetchEnabled();
  });

  srcProject.addEventListener("change", () => {
    const projectKey = (srcProject.value || "").trim().toUpperCase();
    srcProject.value = projectKey;
    populateBoards(srcBoard, projectKey);
    setDisabled(srcBoard, false);
    setFetchEnabled();
  });
  srcBoard.addEventListener("change", setFetchEnabled);

  fetchRuleBtn.addEventListener("click", async () => {
    clear(fetchMsg);
    clear(copyMsg);
    ruleDetailsCard.classList.add("d-none");
    confirmSection.classList.add("d-none");
    step2.classList.add("d-none");
    fetchedRuleId = null;
    fetchedRuleJson = null;
    fetchCompleted = false;
    confirmCompleted = false;
    setDisabled(copyRuleBtn, true);

    lockUi();
    try {
      const data = await postJson("/api/automation/rule-copier/fetch", {
        project_key: srcProject.value.trim().toUpperCase(),
        board_id: Number(srcBoard.value),
        rule_id: Number((ruleId.value || "").trim())
      });
      if (!data.ok) {
        showAlert(fetchMsg, "danger", data.error || "Failed to fetch rule.");
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
    } catch (error) {
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
    setDisabled(dstBoard, false);
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
        rule_json: fetchedRuleJson
      });
      if (!data.ok) {
        showAlert(copyMsg, "danger", data.error || "Copy failed.");
        return;
      }
      showAlert(copyMsg, "success", data.message || "Rule copied.");
    } catch (error) {
      showAlert(copyMsg, "danger", "Network/Unexpected error while copying rule.");
    } finally {
      unlockUi();
    }
  });

  applyUiState();
})();
