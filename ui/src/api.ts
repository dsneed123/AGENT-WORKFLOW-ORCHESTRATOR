/** One place that talks to the studio. Token rules match the pre-React page.
 *
 * Nothing about the backend is baked into the bundle. Where the API lives is
 * decided when the page loads, first hit wins:
 *
 *   1. ?api=http://host:port on the URL   (saved, so later visits need no query)
 *   2. awo-api in localStorage            (what the connect screen writes)
 *   3. "api" in awo-config.json           (sits beside index.html; edit it on the
 *                                          static host, no rebuild)
 *   4. this page's own origin             (the studio serving ui/dist itself)
 */
/** Accept what a person actually types: "gx10.local:8740", a trailing slash, stray spaces. */
const clean = (value: string) => {
  const text = value.trim().replace(/\/+$/, "");
  if (!text) return "";
  return /^https?:\/\//i.test(text) ? text : `http://${text}`;
};

let base = "";
let token = "";

export const apiBase = () => base;
export const apiToken = () => token;

export function setToken(given: string) {
  token = given;
  localStorage.setItem("awo-token", given);
}

export function setApi(url: string) {
  base = clean(url);
  if (base) localStorage.setItem("awo-api", base);
  else localStorage.removeItem("awo-api");
}

/** Resolve the API address before the first request. Runs once, from App. */
export async function boot() {
  const params = new URLSearchParams(location.search);
  if (params.get("api")) setApi(params.get("api")!);
  if (params.get("token")) setToken(params.get("token")!);
  token = token || localStorage.getItem("awo-token") || "";
  if (base) return;

  const saved = localStorage.getItem("awo-api");
  if (saved) {
    base = clean(saved);
    return;
  }
  try {
    const res = await fetch(new URL("awo-config.json", document.baseURI), { cache: "no-store" });
    if (res.ok) {
      const config = (await res.json()) as { api?: string };
      if (config?.api) base = clean(String(config.api));
    }
  } catch {
    /* no config file on this host: fall through to the page's own origin */
  }
}

/** Try an address and token without saving them. Returns a reason, or null when it works. */
export async function check(url: string, given: string): Promise<string | null> {
  const target = clean(url);
  try {
    const res = await fetch(target + "/api/workflows", {
      cache: "no-store",
      headers: given ? { "X-AWO-Token": given } : {},
    });
    if (res.status === 401) return given ? "that token was not accepted" : "this studio needs its access token";
    if (!res.ok) return `that address answered ${res.status}`;
    await res.json();
    return null;
  } catch {
    return "no answer — check the host, the port, and that the studio is running with --host 0.0.0.0";
  }
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function call<T>(path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = token ? { "X-AWO-Token": token } : {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(base + path, body === undefined
    ? { headers }
    : { method: "POST", headers, body: JSON.stringify(body) });
  if (res.status === 401) {
    const given = window.prompt("This studio needs its access token:");
    if (given) {
      setToken(given);
      return call<T>(path, body);
    }
    throw new ApiError("this studio needs its access token", 401);
  }
  if (!res.ok) throw new ApiError(`${path} answered ${res.status}`, res.status);
  return (await res.json()) as T;
}

export const get = <T>(path: string) => call<T>(path);
export const post = <T>(path: string, body: unknown) => call<T>(path, body);

export function streamUrl(folder: string | null, after: number, run?: string | null) {
  const query = new URLSearchParams();
  if (folder) query.set("w", folder);
  if (after) query.set("after", String(after));
  if (run) query.set("run", run);
  if (token) query.set("token", token);
  return `${base}/api/events?${query.toString()}`;
}

export const q = (value: string) => encodeURIComponent(value);
