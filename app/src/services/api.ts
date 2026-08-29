import { AWS_CONFIG } from "../config/aws";
import { getCurrentSession, getIdToken } from "./auth";

const BASE_URL = AWS_CONFIG.api.baseUrl;

// Every handler in this backend returns { message: "..." } on error — surface
// that instead of a bare status code, since it's usually the actual reason
// (e.g. the publish endpoint's narration-gate explanation), not just "failed".
async function extractErrorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (body && typeof body.message === "string") return body.message;
  } catch {
    // Body wasn't JSON (or was empty) — fall through to the generic message.
  }
  return `API error: ${res.status}`;
}

async function getAuthHeaders(): Promise<Record<string, string>> {
  const session = await getCurrentSession();
  if (!session) throw new Error("Not authenticated");
  return {
    "Content-Type": "application/json",
    Authorization: getIdToken(session),
  };
}

export async function apiGet<T = any>(path: string): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${BASE_URL}${path}`, { headers });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export async function apiPost<T = any>(path: string, body: any, requireAuth = true): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (requireAuth) {
    const authHeaders = await getAuthHeaders();
    Object.assign(headers, authHeaders);
  }
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export async function apiPut<T = any>(path: string, body: any): Promise<T> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "PUT",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
  return res.json();
}

export async function apiDelete(path: string): Promise<void> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "DELETE",
    headers,
  });
  if (!res.ok) throw new Error(await extractErrorMessage(res));
}
