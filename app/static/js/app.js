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

    return fetch("/client-log", {
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
