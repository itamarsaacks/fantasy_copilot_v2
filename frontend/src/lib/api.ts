/**
 * Tiny fetch wrapper for talking to the FastAPI backend.
 *
 * - credentials: "include" so the JWT cookie flows on every request
 * - Throws ApiError with the parsed body on non-2xx
 */

/**
 * Empty string => relative URLs (Next.js rewrites proxy to backend on the
 * SAME origin as the frontend). This is what we use in dev (whether through
 * localhost:3000 or via ngrok tunnel) so cookies set by the backend land on
 * the same domain the browser is using. Set NEXT_PUBLIC_API_URL only when
 * you explicitly want the browser to talk to a different origin.
 */
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public body: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type RequestOpts = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  /** When true, a 401 is silently translated to `null`. Used by /auth/me. */
  silent401?: boolean;
};

export async function api<T>(path: string, opts: RequestOpts = {}): Promise<T> {
  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const res = await fetch(url, {
    method: opts.method ?? "GET",
    credentials: "include",
    headers: opts.body
      ? { "Content-Type": "application/json", Accept: "application/json" }
      : { Accept: "application/json" },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
  });

  let body: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!res.ok) {
    if (res.status === 401 && opts.silent401) {
      return null as T;
    }
    const detail =
      (body as { detail?: string } | null)?.detail ??
      `HTTP ${res.status}`;
    throw new ApiError(detail, res.status, body);
  }

  return body as T;
}

export const apiBase = API_BASE;
