import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";
import { API_URL } from "@/lib/env";
import { readAuth, clearAuth } from "@/lib/auth/storage";

export const http = axios.create({
  baseURL: API_URL,
  headers: { "Content-Type": "application/json" },
});

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const auth = readAuth();
  if (auth?.token) {
    config.headers.set("Authorization", `Bearer ${auth.token}`);
  }
  return config;
});

http.interceptors.response.use(
  (res) => res,
  (err: AxiosError) => {
    if (err.response?.status === 401) {
      clearAuth();
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.assign("/login");
      }
    }
    return Promise.reject(err);
  },
);

export type ApiError = {
  status: number;
  message: string;
  messages: string[];
  fieldErrors: Record<string, string>;
};

const FIELD_PREFIX = /^([\w.]+):\s(.+)$/;

export function asApiError(err: unknown): ApiError {
  if (err instanceof AxiosError) {
    const data = err.response?.data as { detail?: unknown } | undefined;
    const detail = data?.detail;
    const raw = typeof detail === "string" ? detail : (err.response ? `Permintaan gagal (HTTP ${err.response.status})` : "Tidak dapat terhubung ke server");
    const messages = raw.split("; ").filter(Boolean);
    const fieldErrors: Record<string, string> = {};
    for (const m of messages) {
      const match = FIELD_PREFIX.exec(m);
      if (match) fieldErrors[match[1]] = match[2];
    }
    return { status: err.response?.status ?? 0, message: messages.join("\n"), messages, fieldErrors };
  }
  return { status: 0, message: "Terjadi kesalahan yang tidak diketahui", messages: ["Terjadi kesalahan yang tidak diketahui"], fieldErrors: {} };
}
