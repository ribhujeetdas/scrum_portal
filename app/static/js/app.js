(function () {
  let requestCounter = 0;

  function getMeta(name) {
    const meta = document.querySelector(`meta[name="${name}"]`);
    return meta ? meta.getAttribute("content") || "" : "";
  }

  function setMeta(name, value) {
    let meta = document.querySelector(`meta[name="${name}"]`);
    if (!meta) {
      meta = document.createElement("meta");
      meta.setAttribute("name", name);
      document.head.appendChild(meta);
    }
    meta.setAttribute("content", value || "");
  }

  function randomHex(length) {
    const bytes = new Uint8Array(Math.ceil(length / 2));
    if (window.crypto && window.crypto.getRandomValues) {
      window.crypto.getRandomValues(bytes);
    } else {
      for (let i = 0; i < bytes.length; i += 1) {
        bytes[i] = Math.floor(Math.random() * 256);
      }
    }
    return Array.from(bytes)
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("")
      .slice(0, length);
  }

  function newRequestId(prefix) {
    requestCounter += 1;
    const base = getMeta("request-id") || randomHex(12);
    return `${prefix || "ui"}-${base}-${requestCounter}-${randomHex(6)}`.slice(0, 64);
  }

  function escapeHtml(value) {
    return String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;"
    }[ch]));
  }

  function compactError(error) {
    if (!error) return "";
    if (typeof error === "string") return error.slice(0, 500);
    return (error.message || String(error)).slice(0, 500);
  }

  function logClientEvent(event, details) {
    const csrfToken = getMeta("csrf-token");
    const payload = {
      event: String(event || "client.event").slice(0, 80),
      message: compactError(details && details.message ? details.message : details),
      url: window.location.href,
      userAgent: navigator.userAgent
    };

    return fetch("/api/client-log", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
        "X-Request-ID": newRequestId("client")
      },
      body: JSON.stringify(payload),
      keepalive: true
    }).catch(() => {});
  }

  function normalizeToastKind(kind) {
    if (["success", "danger", "warning", "info"].includes(kind)) return kind;
    return "info";
  }

  function showToast(message, kind, delay) {
    const container = document.getElementById("portalToastContainer");
    if (!container || !window.bootstrap) {
      return;
    }

    const safeKind = normalizeToastKind(kind || "info");
    const toastEl = document.createElement("div");
    toastEl.className = `toast portal-toast portal-toast-${safeKind}`;
    toastEl.setAttribute("role", "alert");
    toastEl.setAttribute("aria-live", "assertive");
    toastEl.setAttribute("aria-atomic", "true");
    toastEl.setAttribute("data-bs-delay", String(delay || 4500));
    toastEl.innerHTML = `
      <div class="d-flex align-items-center">
        <div class="toast-body">${escapeHtml(message)}</div>
        <button type="button" class="btn-close me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    `;
    container.appendChild(toastEl);

    const toast = bootstrap.Toast.getOrCreateInstance(toastEl, {
      autohide: true,
      delay: delay || 4500
    });
    toastEl.addEventListener("hidden.bs.toast", () => toastEl.remove());
    toast.show();
  }

  async function apiFetch(url, options) {
    const requestId = newRequestId("ui");
    const opts = Object.assign({}, options || {});
    const headers = new Headers(opts.headers || {});

    if (!headers.has("X-CSRFToken")) {
      headers.set("X-CSRFToken", getMeta("csrf-token"));
    }
    if (!headers.has("X-Request-ID")) {
      headers.set("X-Request-ID", requestId);
    }
    if (opts.body && !(opts.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }

    opts.headers = headers;

    try {
      const response = await fetch(url, opts);
      const responseRequestId = response.headers.get("X-Request-ID");
      if (responseRequestId) {
        setMeta("request-id", responseRequestId);
      }
      if (!response.ok) {
        logClientEvent("fetch.http_error", {
          message: `${opts.method || "GET"} ${url} -> HTTP ${response.status}`
        });
      }
      return response;
    } catch (error) {
      logClientEvent("fetch.network_error", {
        message: `${opts.method || "GET"} ${url}: ${compactError(error)}`
      });
      throw error;
    }
  }

  window.portalApiFetch = apiFetch;
  window.portalLogClientEvent = logClientEvent;
  window.portalNewRequestId = newRequestId;
  window.portalEscapeHtml = escapeHtml;
  window.portalShowToast = showToast;

  function formatCountdown(seconds) {
    const safeSeconds = Math.max(0, Number(seconds) || 0);
    const mins = Math.floor(safeSeconds / 60);
    const secs = safeSeconds % 60;
    return `${mins}:${String(secs).padStart(2, "0")}`;
  }

  function startSessionMonitor() {
    if (document.body.getAttribute("data-authenticated") !== "true" || !window.bootstrap) {
      return;
    }

    const modalEl = document.getElementById("sessionExpiryModal");
    const countdownEl = document.getElementById("sessionCountdown");
    const extendBtn = document.getElementById("sessionExtendBtn");
    const logoutBtn = document.getElementById("sessionLogoutBtn");
    const logoutForm = document.getElementById("sessionLogoutForm");
    if (!modalEl || !countdownEl || !extendBtn || !logoutBtn || !logoutForm) {
      return;
    }

    const modal = bootstrap.Modal.getOrCreateInstance(modalEl, {
      backdrop: "static",
      keyboard: false
    });
    let expiresAt = 0;
    let countdownTimer = null;
    let pollTimer = null;
    let modalVisible = false;

    function clearCountdown() {
      if (countdownTimer) {
        window.clearInterval(countdownTimer);
        countdownTimer = null;
      }
    }

    function updateCountdown() {
      const remaining = Math.max(0, Math.floor(expiresAt - Date.now() / 1000));
      countdownEl.textContent = formatCountdown(remaining);
      if (remaining <= 0) {
        window.location.href = "/auth/login";
      }
    }

    function showWarning() {
      if (!modalVisible) {
        modal.show();
        modalVisible = true;
      }
      clearCountdown();
      updateCountdown();
      countdownTimer = window.setInterval(updateCountdown, 1000);
    }

    function hideWarning() {
      clearCountdown();
      if (modalVisible) {
        modal.hide();
        modalVisible = false;
      }
    }

    async function pollStatus() {
      try {
        const response = await apiFetch("/api/session/status", { method: "GET" });
        if (response.status === 401) {
          window.location.href = "/auth/login";
          return;
        }
        const data = await response.json();
        if (!data.authenticated || data.expired) {
          window.location.href = data.redirect_url || "/auth/login";
          return;
        }
        expiresAt = Number(data.expires_at || 0);
        if (data.show_warning) {
          showWarning();
        } else {
          hideWarning();
        }
      } catch (error) {
        logClientEvent("session.status_error", error);
      }
    }

    extendBtn.addEventListener("click", async () => {
      extendBtn.setAttribute("disabled", "disabled");
      try {
        const response = await apiFetch("/api/session/extend", { method: "POST" });
        if (response.status === 401) {
          window.location.href = "/auth/login";
          return;
        }
        const data = await response.json();
        expiresAt = Number(data.expires_at || 0);
        hideWarning();
        showToast("Session extended.", "success");
      } catch (error) {
        showToast("Unable to extend session. Please try again.", "danger");
        logClientEvent("session.extend_error", error);
      } finally {
        extendBtn.removeAttribute("disabled");
      }
    });

    logoutBtn.addEventListener("click", () => {
      logoutForm.submit();
    });

    pollStatus();
    pollTimer = window.setInterval(pollStatus, 15000);
    window.addEventListener("beforeunload", () => {
      if (pollTimer) window.clearInterval(pollTimer);
      clearCountdown();
    });
  }

  const loadedFeatureScripts = new Set();

  function loadFeatureScripts() {
    document.querySelectorAll("[data-feature-script-src]").forEach((el) => {
      const src = el.getAttribute("data-feature-script-src");
      if (!src || loadedFeatureScripts.has(src)) return;
      loadedFeatureScripts.add(src);
      const script = document.createElement("script");
      script.src = src;
      script.defer = true;
      script.setAttribute("data-feature-script", "true");
      document.body.appendChild(script);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".portal-toast").forEach((toastEl) => {
      const toast = bootstrap.Toast.getOrCreateInstance(toastEl, {
        autohide: true,
        delay: Number(toastEl.getAttribute("data-bs-delay") || 4500)
      });
      toastEl.addEventListener("hidden.bs.toast", () => toastEl.remove());
      toast.show();
    });
    loadFeatureScripts();
    startSessionMonitor();
  });

  window.addEventListener("error", (event) => {
    logClientEvent("window.error", {
      message: `${event.message || "error"} at ${event.filename || ""}:${event.lineno || 0}`
    });
  });

  window.addEventListener("unhandledrejection", (event) => {
    logClientEvent("window.unhandledrejection", {
      message: compactError(event.reason)
    });
  });
})();
