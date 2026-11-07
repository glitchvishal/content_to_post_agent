// Typed client for the Content-to-Post FastAPI backend (api/main.py, api/runs.py).

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

export type Platform = "linkedin" | "x";
export type RunStatus = "queued" | "running" | "awaiting_review" | "completed" | "rejected" | "failed";

export const ACTIVE_STATUSES: RunStatus[] = ["queued", "running"];
export const isActive = (s: RunStatus) => ACTIVE_STATUSES.includes(s);

export const PLATFORM_META: Record<Platform, { name: string; limit: number }> = {
  linkedin: { name: "LinkedIn", limit: 1300 },
  x: { name: "X (Twitter)", limit: 280 },
};

export interface RunRequest {
  url?: string;
  text?: string;
  platforms: Platform[];
  auto_approve?: boolean;
}

export interface RunCreated {
  run_id: string;
  status: RunStatus;
  links: { self: string; events: string; review: string };
}

export interface KeyPoint {
  point: string;
  chunk_ids: number[];
}

export interface Plan {
  angle: string | null;
  audience: string | null;
  platforms: Platform[] | null;
  key_points: KeyPoint[] | null;
}

export interface Critique {
  faithfulness: number;
  platform_fit: number;
  hook: number;
  unsupported_claims: string[];
  feedback: string;
  chars: number;
  passed: boolean;
}

export interface ScheduledPost {
  id?: string;
  platform: Platform;
  text: string;
  scheduled_at_utc: string;
  status: string;
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  llm_calls: number;
  cost_usd: number;
}

export interface RunError {
  type: string;
  message: string;
  node: string | null;
}

export interface RunView {
  run_id: string;
  status: RunStatus;
  error: RunError | null;
  created_at: string;
  updated_at: string;
  source: { url: string | null; text_chars: number; platforms: Platform[] | null };
  title: string | null;
  source_truncated: boolean | null;
  plan: Plan | null;
  posts: Partial<Record<Platform, string>> | null;
  critique: Partial<Record<Platform, Critique>> | null;
  revisions: number;
  review: { decision: "approve" | "edit" | "reject"; reason?: string | null } | null;
  scheduled: ScheduledPost[] | null;
  usage: Usage;
}

export interface ReviewRequest {
  decision: "approve" | "edit" | "reject";
  posts?: Partial<Record<Platform, string>>;
  reason?: string;
  schedule_at?: string; // ISO datetime with timezone
}

/** One Server-Sent Event, already parsed. `id` is the SSE event id (an index into the run's event log). */
export interface RunEvent {
  id: number;
  event: "status" | "node" | "review" | "review_required";
  data: {
    run_id: string;
    ts: string;
    status?: RunStatus;
    error?: RunError | null;
    node?: string;
    elapsed_s?: number;
    decision?: string;
    [key: string]: unknown;
  };
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number | null,
  ) {
    super(message);
  }
}

/** FastAPI errors: `detail` is a string (HTTPException) or a list of {loc, msg} (request validation). */
function detailToMessage(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const msg = typeof d?.msg === "string" ? d.msg.replace(/^Value error, /, "") : "Invalid value";
        const field = Array.isArray(d?.loc) ? d.loc.filter((p: unknown) => p !== "body").join(".") : "";
        return field ? `${field}: ${msg}` : msg;
      })
      .join(" ");
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...init?.headers },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      `Cannot reach the API at ${API_URL}. Is the backend running, and is this site's origin listed in ALLOWED_ORIGINS?`,
      null,
    );
  }
  if (!res.ok) {
    let message: string | null = null;
    try {
      message = detailToMessage((await res.json()).detail);
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(message ?? `Request failed (HTTP ${res.status}).`, res.status);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<{ status: string; llm_provider: string; model: string }>("/health"),
  createRun: (body: RunRequest) => request<RunCreated>("/runs", { method: "POST", body: JSON.stringify(body) }),
  getRun: (id: string) => request<RunView>(`/runs/${id}`),
  review: (id: string, body: ReviewRequest) =>
    request<RunView>(`/runs/${id}/review`, { method: "POST", body: JSON.stringify(body) }),
  eventsUrl: (id: string) => `${API_URL}/runs/${id}/events`,
};
