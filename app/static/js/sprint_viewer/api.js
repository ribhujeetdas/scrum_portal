export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

export async function requestJson(apiFetch, url, options = {}, externalSignal = null) {
  const timeoutController = new AbortController();
  const timer = window.setTimeout(() => timeoutController.abort(), 15000);
  const requestController = new AbortController();
  const forwardAbort = () => requestController.abort();
  timeoutController.signal.addEventListener("abort", forwardAbort, { once: true });
  externalSignal?.addEventListener("abort", forwardAbort, { once: true });
  try {
    if (externalSignal?.aborted) requestController.abort();
    const response = await apiFetch(url, { ...options, signal: requestController.signal });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok && response.status !== 202) {
      throw new ApiError(
        payload?.error?.message || `Request failed with HTTP ${response.status}`,
        response.status,
        payload,
      );
    }
    return { status: response.status, payload, retryAfter: response.headers.get("Retry-After") };
  } finally {
    window.clearTimeout(timer);
    timeoutController.signal.removeEventListener("abort", forwardAbort);
    externalSignal?.removeEventListener("abort", forwardAbort);
  }
}

export function postJson(apiFetch, url, body, signal) {
  return requestJson(apiFetch, url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }, signal);
}

export function getJson(apiFetch, url, signal) {
  return requestJson(apiFetch, url, { method: "GET" }, signal);
}

export function pollDelay(unchangedCount, retryAfter) {
  if (retryAfter) return Math.min(30000, Math.max(1000, Number(retryAfter) * 1000));
  const base = [1500, 2000, 3000, 5000][Math.min(unchangedCount, 3)];
  const hiddenBase = document.hidden ? 10000 : base;
  return Math.round(hiddenBase * (0.8 + Math.random() * 0.4));
}
