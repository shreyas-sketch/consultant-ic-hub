// Transport: one fetch wrapper for every call to the backend. Same origin, cookie auth.

export class ApiError extends Error {
  constructor(code, message, status, extra, requestId) {
    super(message);
    this.code = code;
    this.status = status;
    this.extra = extra || {};
    this.requestId = requestId;
  }
}

const PLAIN = "Something went wrong. Please try again.";
const PUBLIC_PREFIXES = ["/login", "/c/", "/admin/login"];

function goToLogin() {
  const here = location.pathname + location.search;
  if (PUBLIC_PREFIXES.some((p) => location.pathname.startsWith(p))) return;
  // The Admin screen has its own (email) sign-in; everything else uses the phone-code login.
  if (location.pathname.startsWith("/admin")) location.href = "/admin/login";
  else location.href = `/login?next=${encodeURIComponent(here)}`;
}

export async function req(method, url, body) {
  let r;
  try {
    r = await fetch(url, {
      method,
      credentials: "include",
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("network", "You seem to be offline. Check your connection and try again.", 0);
  }
  let data = null;
  try {
    data = await r.json();
  } catch {
    data = null;
  }
  if (!r.ok) {
    const e = data?.error || {};
    if (r.status === 401) goToLogin();
    throw new ApiError(e.code || "error", e.message || PLAIN, r.status, e.extra, e.request_id || r.headers.get("x-request-id"));
  }
  return data;
}

/** Run one backend action: POST /api/a/<name>. */
export const act = (name, body = {}) => req("POST", `/api/a/${name}`, body);
export const get = (url) => req("GET", url);
export const post = (url, body = {}) => req("POST", url, body);
