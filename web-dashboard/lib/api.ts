const DEFAULT_API_BASE_URL = 'http://localhost:8000';

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ||
  process.env.BACKEND_URL ||
  DEFAULT_API_BASE_URL;

export function getApiBaseUrl(): string {
  return API_BASE_URL.replace(/\/$/, '');
}
