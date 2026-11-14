export type Task = { id: string; title: string; repository_url: string; issue_number: number | null; status: string; created_at: string; workflow: {current_step?: string; issue_details?: {title: string; body: string}; retry_count?: number; changed_files?: string[]; review_feedback?: string; investigation_summary?: string; pr_url?: string; error?: string}; approval: {hash: string; payload: unknown; plan?: unknown} | null }
export type Activity = {agent: string; status: string; timestamp: string; tool?: string; error_type?: string; retry_attempt: number}
export type Tests = {status: string; exit_code?: number; duration_seconds?: number; output: string}
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL || ''}/api${path}`, {...init, headers: {'Content-Type': 'application/json', Authorization: `Bearer ${sessionStorage.getItem('devpilot-token') || ''}`, ...init?.headers}, signal: AbortSignal.timeout(10000)})
  if (!response.ok) {const body = await response.json().catch(() => ({})); throw new Error(typeof body.detail === 'string' ? body.detail : response.status >= 500 ? 'Backend unavailable. Check that FastAPI is running and its services are reachable.' : `Request failed (${response.status}). Check your inputs.`)}
  return response.json() as Promise<T>
}
