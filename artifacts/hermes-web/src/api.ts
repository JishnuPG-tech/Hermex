export type AuthStatus = {
  auth_enabled: boolean;
  password_auth_enabled: boolean;
  api_key_auth_enabled: boolean;
  logged_in: boolean;
};

export type SessionSummary = {
  id: string;
  title?: string;
  created_at?: string;
  updated_at?: string;
  model?: string;
  is_streaming?: boolean;
  active_stream_id?: string | null;
};

export type SessionDetail = SessionSummary & {
  messages?: Array<{
    id?: string;
    role: "user" | "assistant" | "system";
    content?: string;
    timestamp?: string;
    reasoning?: Array<{ text?: string }>;
  }>;
};

export type StreamEvent = {
  event: string;
  data: Record<string, unknown>;
  seq?: number;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
    ...init,
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed with HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export const api = {
  authStatus: () => request<AuthStatus>("/api/auth/status"),
  login: (password: string) =>
    request<{ ok: boolean; authenticated: boolean }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  logout: () =>
    request<{ ok: boolean }>("/api/auth/logout", {
      method: "POST",
    }),
  sessions: () =>
    request<{ sessions: SessionSummary[] }>("/api/sessions"),
  session: (sessionId: string) =>
    request<{ session: SessionDetail }>(
      `/api/session?session_id=${encodeURIComponent(sessionId)}&messages=1`,
    ),
  createSession: () =>
    request<{ ok: boolean; session: SessionSummary }>("/api/session/new", {
      method: "POST",
      body: JSON.stringify({ title: "New conversation" }),
    }),
  startChat: (sessionId: string | null, message: string) =>
    request<{ stream_id: string; session_id: string }>("/api/chat/start", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        message,
      }),
    }),
  cancelChat: (streamId: string) =>
    request<{ ok: boolean }>(
      `/api/chat/cancel?stream_id=${encodeURIComponent(streamId)}`,
      { method: "POST" },
    ),
};

export function openStream(
  streamId: string,
  afterSeq: number,
  onEvent: (event: StreamEvent) => void,
  onError: () => void,
): EventSource {
  const query = new URLSearchParams({
    stream_id: streamId,
    replay: "1",
    ...(afterSeq > 0 ? { after_seq: String(afterSeq) } : {}),
  });
  const source = new EventSource(`/api/chat/stream?${query.toString()}`);
  const eventNames = [
    "token",
    "reasoning",
    "tool_call",
    "tool_result",
    "error",
    "cancel",
    "done",
    "stream_end",
  ];

  for (const name of eventNames) {
    source.addEventListener(name, (event) => {
      const message = event as MessageEvent<string>;
      try {
        onEvent({
          event: name,
          data: JSON.parse(message.data) as Record<string, unknown>,
          seq: Number(message.lastEventId.split(":").pop() || 0),
        });
      } catch {
        onEvent({ event: "error", data: { error: "Invalid stream event" } });
      }
    });
  }

  source.onerror = onError;
  return source;
}