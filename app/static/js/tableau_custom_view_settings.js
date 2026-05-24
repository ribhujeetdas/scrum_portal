(function () {
  const page = document.getElementById("tableauCustomViewSettingsPage");
  if (!page) return;

  const modalEl = document.getElementById("customViewDeleteConfirmModal");
  const messageEl = document.getElementById("customViewDeleteMessage");
  const detailEl = document.getElementById("customViewDeleteDetail");
  const confirmBtn = document.getElementById("customViewDeleteConfirm");
  const cancelBtn = document.getElementById("customViewDeleteCancel");
  let pendingForm = null;
  let pendingSubmitter = null;

  function showDeleteModal(form, submitter) {
    const viewName = form.getAttribute("data-view-name") || "(Unnamed)";
    const viewId = form.getAttribute("data-view-id") || "";
    pendingForm = form;
    pendingSubmitter = submitter || null;
    messageEl.textContent = `Delete custom view "${viewName}"?`;
    detailEl.textContent = `Custom view ID: ${viewId}`;
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
    window.setTimeout(() => cancelBtn.focus(), 150);
  }

  if (confirmBtn) {
    confirmBtn.addEventListener("click", () => {
      if (!pendingForm) return;
      const form = pendingForm;
      const submitter = pendingSubmitter;
      pendingForm = null;
      pendingSubmitter = null;
      bootstrap.Modal.getOrCreateInstance(modalEl).hide();
      form.dataset.deleteConfirmed = "true";
      if (form.requestSubmit && submitter) form.requestSubmit(submitter);
      else form.submit();
    });
  }

  page.querySelectorAll(".js-cv-delete-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.deleteConfirmed === "true") {
        delete form.dataset.deleteConfirmed;
        return;
      }
      event.preventDefault();
      showDeleteModal(form, event.submitter);
    });
  });
})();
