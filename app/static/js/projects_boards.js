(function () {
  const page = document.getElementById("projectsBoardsPage");
  if (!page) return;

  const modalEl = document.getElementById("deleteConfirmModal");
  const titleEl = document.getElementById("deleteConfirmTitle");
  const messageEl = document.getElementById("deleteConfirmMessage");
  const detailEl = document.getElementById("deleteConfirmDetail");
  const deleteBtn = document.getElementById("deleteConfirmDelete");
  const cancelBtn = document.getElementById("deleteConfirmCancel");
  let pendingForm = null;
  let pendingSubmitter = null;

  function showDeleteModal(options) {
    pendingForm = options.form;
    pendingSubmitter = options.submitter || null;
    titleEl.textContent = options.title;
    messageEl.textContent = options.message;
    detailEl.textContent = options.detail;
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
    window.setTimeout(() => cancelBtn.focus(), 150);
  }

  if (deleteBtn) {
    deleteBtn.addEventListener("click", () => {
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

  page.querySelectorAll(".js-project-delete-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.deleteConfirmed === "true") {
        delete form.dataset.deleteConfirmed;
        return;
      }
      event.preventDefault();
      const projectKey = form.getAttribute("data-project-key") || "";
      const boardCount = Number(form.getAttribute("data-board-count") || "0");
      showDeleteModal({
        form: form,
        submitter: event.submitter,
        title: "Delete project",
        message: `Delete project ${projectKey}?`,
        detail: `This will remove the project and ${boardCount} saved board${boardCount === 1 ? "" : "s"} from your settings.`
      });
    });
  });

  page.querySelectorAll(".js-board-delete-form").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.deleteConfirmed === "true") {
        delete form.dataset.deleteConfirmed;
        return;
      }
      event.preventDefault();
      const projectKey = form.getAttribute("data-project-key") || "";
      const boardId = form.getAttribute("data-board-id") || "";
      const boardName = form.getAttribute("data-board-name") || "";
      const boardCount = Number(form.getAttribute("data-board-count") || "0");
      const removesProject = boardCount <= 1;
      showDeleteModal({
        form: form,
        submitter: event.submitter,
        title: "Delete board",
        message: `Delete board ${boardName} (${boardId})?`,
        detail: removesProject
          ? `This is the last saved board for project ${projectKey}, so the project will also be removed.`
          : `This will remove only this board from project ${projectKey}.`
      });
    });
  });

  const projectKeyInput = document.getElementById("project_key");
  if (projectKeyInput) {
    projectKeyInput.addEventListener("input", () => {
      projectKeyInput.value = projectKeyInput.value.toUpperCase();
    });
  }
})();
