export type AuthStatus = {
  auth_enabled: boolean;
  password_auth_enabled: boolean;
  api_key_auth_enabled: boolean;
  logged_in: boolean;
};

export type SessionSummary = {
  id: string;
  session_id?: string;
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

export type UploadedFile = {
  id?: string;
  file_name?: string;
  filename?: string;
  path?: string;
  mime?: string;
  size?: number;
  status?: string;
};

export type Project = {
  project_id: string;
  name: string;
  description?: string;
  instructions?: string;
  color?: string | null;
  archived?: boolean;
  created_at?: number;
  updated_at?: number;
  session_count?: number;
  file_count?: number;
  goal_count?: number;
  active_goal_count?: number;
  task_count?: number;
  completed_task_count?: number;
};

export type MemoryRecord = {
  id: string;
  content: string;
  category?: string;
  type?: string;
  source?: string;
  created_at?: number;
  updated_at?: number;
  project_id?: string | null;
  session_id?: string | null;
  confidence?: number | null;
  metadata?: Record<string, unknown>;
};

export type Goal = {
  id: string;
  title: string;
  description?: string;
  status: string;
  priority?: string;
  deadline?: string | null;
  project_id?: string | null;
  task_count?: number;
  completed_task_count?: number;
  progress?: number;
};

export type Task = {
  id: string;
  title: string;
  description?: string;
  status: string;
  priority?: string;
  goal_id?: string | null;
  project_id?: string | null;
  dependencies?: string[];
  started_at?: number | null;
  completed_at?: number | null;
  error?: string | null;
  result?: string | null;
  summary?: string | null;
};

type RawSession = Omit<SessionSummary, "id"> & {
  id?: string;
  session_id?: string;
};

function normalizeSession(session: RawSession): SessionSummary {
  return {
    ...session,
    id: session.id ?? session.session_id ?? "",
  };
}

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
  sessions: async () => {
    const result = await request<{ sessions: RawSession[] }>("/api/sessions");
    return { ...result, sessions: result.sessions.map(normalizeSession) };
  },
  session: (sessionId: string) =>
    request<{ session: RawSession }>(
      `/api/session?session_id=${encodeURIComponent(sessionId)}&messages=1`,
    ).then((result) => ({ session: normalizeSession(result.session) as SessionDetail })),
  createSession: async (projectId?: string | null) => {
    const result = await request<{ ok: boolean; session: RawSession }>("/api/session/new", {
      method: "POST",
      body: JSON.stringify({ title: "New conversation", project_id: projectId ?? undefined }),
    });
    return { ...result, session: normalizeSession(result.session) };
  },
  upload: async (file: File, sessionId: string | null) => {
    const form = new FormData();
    form.append("file", file);
    if (sessionId) form.append("session_id", sessionId);
    const response = await fetch("/api/upload", {
      method: "POST",
      credentials: "include",
      body: form,
    });
    if (!response.ok) {
      throw new Error((await response.text()) || `Upload failed with HTTP ${response.status}`);
    }
    return (await response.json()) as UploadedFile;
  },
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
  moveSession: (sessionId: string, projectId: string | null) =>
    request<{ ok: boolean; session: RawSession }>("/api/session/move", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, project_id: projectId }),
    }),
  projects: () => request<{ projects: Project[] }>("/api/projects"),
  createProject: (payload: { name: string; description?: string; instructions?: string }) =>
    request<{ ok: boolean; project: Project }>("/api/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  project: (projectId: string) =>
    request<{ project: Project & { sessions?: SessionSummary[]; files?: UploadedFile[]; memory?: MemoryRecord[]; goals?: Goal[]; tasks?: Task[] } }>(
      `/api/projects/${encodeURIComponent(projectId)}`,
    ),
  updateProject: (projectId: string, payload: Partial<Project>) =>
    request<{ ok: boolean; project: Project }>(`/api/projects/${encodeURIComponent(projectId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteProject: (projectId: string) =>
    request<{ ok: boolean }>(`/api/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" }),
  memory: (query = "") =>
    request<{ memory: MemoryRecord[]; count: number }>(`/api/memory?q=${encodeURIComponent(query)}`),
  createMemory: (payload: { content: string; category?: string; project_id?: string | null }) =>
    request<{ ok: boolean; memory: MemoryRecord }>("/api/memory", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteMemory: (memoryId: string) =>
    request<{ ok: boolean }>(`/api/memory/${encodeURIComponent(memoryId)}`, { method: "DELETE" }),
  goals: (projectId?: string) =>
    request<{ goals: Goal[] }>(`/api/goals${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""}`),
  createGoal: (payload: { title: string; description?: string; project_id?: string | null }) =>
    request<{ ok: boolean; goal: Goal }>("/api/goals", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  tasks: (filters: { projectId?: string; goalId?: string } = {}) => {
    const params = new URLSearchParams();
    if (filters.projectId) params.set("project_id", filters.projectId);
    if (filters.goalId) params.set("goal_id", filters.goalId);
    return request<{ tasks: Task[] }>(`/api/tasks${params.toString() ? `?${params.toString()}` : ""}`);
  },
  createTask: (payload: { title: string; goal_id?: string; project_id?: string; dependencies?: string[] }) =>
    request<{ ok: boolean; task: Task }>("/api/tasks", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateTask: (taskId: string, payload: Partial<Task>) =>
    request<{ ok: boolean; task: Task }>(`/api/tasks/${encodeURIComponent(taskId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
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