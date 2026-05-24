(function () {
  const page = document.getElementById("tciCustomViewsPage");
  if (!page) return;

  const apiFetch = window.portalApiFetch || window.fetch.bind(window);
  const previewForm = document.getElementById("tciPreviewForm");
  const previewLoader = document.getElementById("previewLoader");
  const selectedCustomView = document.getElementById("selectedCustomViewId");
  const planningModalBody = document.getElementById("planningModalBody");
  const planningModalEl = document.getElementById("planningModal");

  function clear(el) {
    if (el) el.replaceChildren();
  }

  function textNode(text) {
    return document.createTextNode(text === null || text === undefined ? "" : String(text));
  }

  function addLine(parent, label, value, className) {
    const line = document.createElement("div");
    if (className) line.className = className;
    const strong = document.createElement("b");
    strong.textContent = label;
    line.appendChild(strong);
    line.appendChild(textNode(` ${value || ""}`));
    parent.appendChild(line);
    return line;
  }

  function showAlert(kind, text) {
    const alert = document.createElement("div");
    alert.className = `alert alert-${kind} mb-0`;
    alert.textContent = text;
    planningModalBody.replaceChildren(alert);
  }

  function showLoading(featureKey) {
    const wrapper = document.createElement("div");
    wrapper.className = "text-muted";
    wrapper.appendChild(textNode("Fetching Jira link details for "));
    const strong = document.createElement("b");
    strong.textContent = featureKey;
    wrapper.appendChild(strong);
    wrapper.appendChild(textNode("..."));
    planningModalBody.replaceChildren(wrapper);
  }

  function renderPlanningDetails(data) {
    clear(planningModalBody);

    const summary = document.createElement("div");
    summary.className = "mb-2";
    addLine(summary, "Feature Issue Key:", data.feature_key);
    addLine(summary, "Mapped Key:", data.mapped_key);
    addLine(summary, "Application ID:", data.application_id);
    const message = document.createElement("div");
    message.className = "text-muted mt-1";
    message.textContent = data.message || "";
    summary.appendChild(message);
    planningModalBody.appendChild(summary);
    planningModalBody.appendChild(document.createElement("hr"));

    const matches = data.matches || [];
    if (!matches.length) {
      const alert = document.createElement("div");
      alert.className = "alert alert-warning mb-0";
      alert.textContent = "No matching related ticket found for mapped key + application label.";
      planningModalBody.appendChild(alert);
      return;
    }

    const list = document.createElement("div");
    list.className = "list-group";
    matches.forEach((match) => {
      const item = document.createElement("div");
      item.className = "list-group-item";
      const row = document.createElement("div");
      row.className = "d-flex justify-content-between align-items-start";
      const content = document.createElement("div");
      addLine(content, "Related Ticket:", match.inward_issue_key);
      addLine(content, "", `${match.inward_status || ""} - ${match.inward_summary || ""}`, "small text-muted");
      const linkType = match.link_type || {};
      addLine(content, "Link Type:", `${linkType.name || ""} (${linkType.inward || ""} / ${linkType.outward || ""})`, "small");
      addLine(content, "Labels:", (match.labels || []).join(", ") || "-", "small");

      const badgeWrap = document.createElement("div");
      badgeWrap.className = "ms-3 text-end";
      const badge = document.createElement("span");
      badge.className = `badge bg-${match.label_match ? "success" : "warning"}`;
      badge.textContent = `Label Match: ${match.label_match ? "Yes" : "No"}`;
      badgeWrap.appendChild(badge);

      row.appendChild(content);
      row.appendChild(badgeWrap);
      item.appendChild(row);
      list.appendChild(item);
    });
    planningModalBody.appendChild(list);
  }

  async function openPlanningDetails(button) {
    const featureKey = button.getAttribute("data-feature-key") || "";
    const applicationId = button.getAttribute("data-application-id") || "";
    const customViewId = selectedCustomView ? selectedCustomView.value || "" : "";

    showLoading(featureKey);
    bootstrap.Modal.getOrCreateInstance(planningModalEl).show();

    try {
      const response = await apiFetch("/api/reports/tci/link-details", {
        method: "POST",
        body: JSON.stringify({
          custom_view_id: customViewId,
          feature_key: featureKey,
          application_id: applicationId
        })
      });
      const data = await response.json();
      if (!data.ok) {
        showAlert("danger", data.error || "Failed to fetch details.");
        return;
      }
      renderPlanningDetails(data);
    } catch (error) {
      showAlert("danger", "Network/Unexpected error while fetching details.");
    }
  }

  if (previewForm) {
    previewForm.addEventListener("submit", () => {
      if (document.activeElement && document.activeElement.id === "previewBtn" && previewLoader) {
        previewLoader.classList.remove("d-none");
      }
    });
  }

  document.querySelectorAll(".planning-status-link").forEach((button) => {
    button.addEventListener("click", () => openPlanningDetails(button));
  });
})();
