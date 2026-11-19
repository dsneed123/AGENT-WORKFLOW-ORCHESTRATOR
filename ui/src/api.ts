/** One place that talks to the studio. Token rules match the pre-React page. */
const params = new URLSearchParams(location.search);
if (params.get("api")) localStorage.setItem("awo-api", params.get("api")!.replace(/\/$/, ""));
if (params.get("token")) localStorage.setItem("awo-token", params.get("token")!);

export const base = localStorage.getItem("awo-api") || "";
let token = localStorage.getItem("awo-token") || "";

export function setToken(given: string) {
  token = given;
  localStorage.setItem("awo-token", given);
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
