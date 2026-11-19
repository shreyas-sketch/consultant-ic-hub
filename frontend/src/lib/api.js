import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export class ApiError extends Error {
  constructor(code, message, status, extra) {
    super(message);
    this.code = code;
    this.status = status;
    this.extra = extra || {};
  }
}

const PLAIN = "Something went wrong. Please try again.";

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
    if (r.status === 401 && !location.pathname.startsWith("/login") && !location.pathname.startsWith("/c/")) {
      location.href = "/login";
    }
    throw new ApiError(e.code || "error", e.message || PLAIN, r.status, e.extra);
  }
  return data;
}

export const act = (name, body = {}) => req("POST", `/api/a/${name}`, body);
export const get = (url) => req("GET", url);
export const post = (url, body = {}) => req("POST", url, body);

/** Read an action as a query: useAct("projects.search", {q}) */
export function useAct(name, body = {}, opts = {}) {
  return useQuery({ queryKey: [name, body], queryFn: () => act(name, body), ...opts });
}

/** Run an action and refresh what it touches. */
export function useDo(name, { invalidate = [], onSuccess, onError } = {}) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body) => act(name, body),
    onSuccess: (data, vars) => {
      (invalidate.length ? invalidate : [name.split(".")[0]]).forEach((k) =>
        qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).startsWith(k) }),
      );
      onSuccess && onSuccess(data, vars);
    },
    onError,
  });
}

export function useRefresh() {
  const qc = useQueryClient();
  return (...prefixes) =>
    qc.invalidateQueries({ predicate: (q) => !prefixes.length || prefixes.some((p) => String(q.queryKey[0]).startsWith(p)) });
}

export function fileToDataUrl(file) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.onerror = () => rej(new ApiError("file", "That file couldn't be read.", 0));
    r.readAsDataURL(file);
  });
}

export function parseCsv(text) {
  const rows = [];
  let row = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') q = false;
      else cell += ch;
    } else if (ch === '"') q = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && text[i + 1] === "\n") i++;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += ch;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  const [head, ...rest] = rows.filter((r) => r.some((c) => c.trim()));
  if (!head) return [];
  return rest.map((r) => Object.fromEntries(head.map((h, i) => [h.trim(), (r[i] || "").trim()])));
}

export function download(filename, text, type = "text/csv") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = filename;
  a.click();
}
