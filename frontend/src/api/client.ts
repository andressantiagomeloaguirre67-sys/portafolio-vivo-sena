/**
 * Cliente HTTP conectado al Backend Django REST + PostgreSQL 18 (`/api/v1/`).
 * Maneja el token JWT de acceso e inicio de sesión por Documento de Identidad.
 */

const API_BASE = "/api/v1";

export function getAccessToken(): string | null {
  return localStorage.getItem("sena_jwt_access");
}

export function setTokens(access: string, refresh?: string) {
  localStorage.setItem("sena_jwt_access", access);
  if (refresh) {
    localStorage.setItem("sena_jwt_refresh", refresh);
  }
}

export function clearTokens() {
  localStorage.removeItem("sena_jwt_access");
  localStorage.removeItem("sena_jwt_refresh");
}

export async function apiRequest<T = any>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getAccessToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw { status: response.status, data };
  }
  return data as T;
}
