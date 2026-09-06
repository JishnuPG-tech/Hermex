import { FormEvent, ReactElement, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  AuthStatus,
  Goal,
  MemoryRecord,
  openStream,
  Project,
  SessionDetail,
  SessionSummary,
  StreamEvent,
  Task,
  UploadedFile,
  WebUISettings,
} from "./api";

type ToolItem = {
  id: string;
  name: string;
  status: "running" | "complete" | "failed";
  summary: string;
};

type ArtifactItem = {
  id: string;
  name: string;
  type: string;
  content: string;
};

type ChatItem = {
  id: string;
  role: "user" | "assistant";
  content: string;
  reasoning?: string;
  toolCount?: number;
};

type WorkspaceView = "chat" | "projects" | "memory" | "goals" | "tasks" | "settings";

function phase3Date(value?: number | string | null) {
  if (!value) return "—";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function inlineMarkdown(text: string) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g);
  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    const bold = part.match(/^\*\*(.+)\*\*$/);
    if (bold) return <strong key={index}>{bold[1]}</strong>;
    const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link && /^https?:\/\//.test(link[2])) {
      return <a key={index} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    }
    return <span key={index}>{part}</span>;
  });
}

function MarkdownContent({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: ReactElement[] = [];
  let list: string[] = [];
  let code: string[] | null = null;
  let language = "";

  const flushList = () => {
    if (!list.length) return;
    blocks.push(
      <ul key={`list-${blocks.length}`}>
        {list.map((item, index) => <li key={index}>{inlineMarkdown(item)}</li>)}
      </ul>,
    );
    list = [];
  };

  lines.forEach((line, index) => {
    if (line.startsWith("```")) {
      flushList();
      if (code) {
        blocks.push(
          <pre key={`code-${index}`} data-language={language}>
            <code>{code.join("\n")}</code>
          </pre>,
        );
        code = null;
        language = "";
      } else {
        code = [];
        language = line.slice(3).trim();
      }
      return;
    }
    if (code) {
      code.push(line);
      return;
    }
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) {
      list.push(bullet[1]);
      return;
    }
    flushList();
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      const Tag = `h${heading[1].length}` as "h1" | "h2" | "h3";
      blocks.push(<Tag key={`heading-${index}`}>{inlineMarkdown(heading[2])}</Tag>);
    } else if (line.trim()) {
      blocks.push(<p key={`paragraph-${index}`}>{inlineMarkdown(line)}</p>);
    }
  });
  flushList();
  const unfinishedCode = code as string[] | null;
  if (unfinishedCode !== null) {
    blocks.push(<pre key="unfinished-code"><code>{unfinishedCode.join("\n")}</code></pre>);
  }
  return <div className="markdown">{blocks}</div>;
}

type Phase3PanelProps = {
  view: WorkspaceView;
  projects: Project[];
  projectDetail: (Project & { sessions?: SessionSummary[]; files?: UploadedFile[]; memory?: MemoryRecord[]; goals?: Goal[]; tasks?: Task[] }) | null;
  selectedProjectId: string | null;
  memory: MemoryRecord[];
  memoryQuery: string;
  goals: Goal[];
  tasks: Task[];
  loading: boolean;
  error: string | null;
  newProjectName: string;
  newMemoryContent: string;
  newGoalTitle: string;
  newTaskTitle: string;
  onView: (view: WorkspaceView) => void;
  onOpenProject: (projectId: string) => void;
  onCreateProjectChat: () => void;
  onCreateProject: (event: FormEvent) => void;
  onCreateMemory: (event: FormEvent) => void;
  onCreateGoal: (event: FormEvent) => void;
  onCreateTask: (event: FormEvent, goalId?: string) => void;
  onForgetMemory: (memoryId: string) => void;
  onStartTask: (task: Task) => void;
  onCompleteTask: (task: Task) => void;
  setMemoryQuery: (value: string) => void;
  setNewProjectName: (value: string) => void;
  setNewMemoryContent: (value: string) => void;
  setNewGoalTitle: (value: string) => void;
  setNewTaskTitle: (value: string) => void;
};

function Phase3Panel(props: Phase3PanelProps) {
  const {
    view, projects, projectDetail, selectedProjectId, memory, memoryQuery, goals, tasks,
    loading, error, newProjectName, newMemoryContent, newGoalTitle, newTaskTitle,
  } = props;
  const visibleGoals = selectedProjectId ? goals.filter((goal) => goal.project_id === selectedProjectId) : goals;
  const visibleTasks = selectedProjectId ? tasks.filter((task) => task.project_id === selectedProjectId) : tasks;
  const visibleMemory = selectedProjectId
    ? (projectDetail?.memory ?? memory.filter((item) => item.project_id === selectedProjectId))
    : memory;

  return (
    <section className="phase3-shell">
      <header className="workspace-header">
        <div>
          <span className="eyebrow">HERMES WORKSPACE</span>
          <h1>{view === "projects" ? "Projects" : view === "memory" ? "Persistent memory" : view === "tasks" ? "Tasks" : "Goals & task graph"}</h1>
          <p className="muted">Durable state from Hermes, not a local-only dashboard.</p>
        </div>
        {loading && <span className="tool-status">Loading…</span>}
      </header>
      {error && <div className="inline-error">{error}</div>}

      {view === "projects" && (
        <div className="workspace-grid">
          <section className="panel project-list-panel">
            <div className="panel-heading"><h2>Projects</h2><span>{projects.length}</span></div>
            <form className="inline-form" onSubmit={props.onCreateProject}>
              <input value={newProjectName} onChange={(event) => props.setNewProjectName(event.target.value)} placeholder="New project name" aria-label="New project name" />
              <button disabled={!newProjectName.trim()}>Create</button>
            </form>
            <div className="project-list">
              {projects.map((project) => (
                <button className={`project-card ${project.project_id === selectedProjectId ? "selected" : ""}`} key={project.project_id} onClick={() => props.onOpenProject(project.project_id)}>
                  <strong>{project.name}</strong>
                  <span>{project.description || "No description yet"}</span>
                  <small>{project.session_count ?? 0} sessions · {project.goal_count ?? 0} goals · {project.file_count ?? 0} files</small>
                </button>
              ))}
              {!projects.length && <p className="empty-copy">Create a project to keep related conversations, memory, goals, and tasks together.</p>}
            </div>
          </section>

          <section className="panel project-detail-panel">
            {!projectDetail ? (
              <div className="empty-state compact"><div className="empty-symbol">✦</div><h2>Select a project</h2><p>Project details, sessions, files, memory, goals, and tasks will appear here.</p></div>
            ) : (
              <>
                <div className="panel-heading"><div><span className="eyebrow">PROJECT</span><h2>{projectDetail.name}</h2></div><span className="project-dot" /></div>
                <p className="detail-copy">{projectDetail.description || "No description yet."}</p>
                {projectDetail.instructions && <details className="instructions"><summary>Instructions</summary><p>{projectDetail.instructions}</p></details>}
                <div className="stat-row">
                  <div><strong>{projectDetail.session_count ?? 0}</strong><span>Sessions</span></div>
                  <div><strong>{projectDetail.file_count ?? 0}</strong><span>Files</span></div>
                  <div><strong>{projectDetail.goal_count ?? 0}</strong><span>Goals</span></div>
                  <div><strong>{projectDetail.task_count ?? 0}</strong><span>Tasks</span></div>
                </div>
                <div className="detail-section"><div className="panel-heading"><h3>Recent sessions</h3><div className="panel-actions"><button className="text-button" onClick={props.onCreateProjectChat}>＋ New chat</button><button className="text-button" onClick={() => props.onView("chat")}>Open chat</button></div></div>
                  {(projectDetail.sessions ?? []).slice(0, 5).map((session) => <div className="compact-row" key={session.id}><span>{session.title || "Untitled conversation"}</span><small>{phase3Date(session.updated_at)}</small></div>)}
                  {!projectDetail.sessions?.length && <p className="empty-copy">No sessions are assigned to this project.</p>}
                </div>
                <div className="detail-section"><div className="panel-heading"><h3>Project memory</h3><button className="text-button" onClick={() => props.onView("memory")}>View all</button></div>
                  {(projectDetail.memory ?? []).slice(0, 3).map((item) => <div className="memory-row" key={item.id}><span>{item.content}</span><button className="forget-button" onClick={() => props.onForgetMemory(item.id)}>Forget</button></div>)}
                  {!projectDetail.memory?.length && <p className="empty-copy">No project memory recorded.</p>}
                </div>
              </>
            )}
          </section>
        </div>
      )}

      {view === "memory" && (
        <section className="panel wide-panel">
          <div className="memory-toolbar">
            <input value={memoryQuery} onChange={(event) => props.setMemoryQuery(event.target.value)} placeholder="Search memory…" aria-label="Search memory" />
            <form className="memory-create" onSubmit={props.onCreateMemory}>
              <input value={newMemoryContent} onChange={(event) => props.setNewMemoryContent(event.target.value)} placeholder="Save a durable fact…" aria-label="Memory content" />
              <button disabled={!newMemoryContent.trim()}>Remember</button>
            </form>
          </div>
          <div className="memory-list">
            {visibleMemory.map((item) => (
              <article className="memory-item" key={item.id}>
                <div><span className="memory-type">{item.type || "memory"}</span><span className="memory-source">{item.source || "WebUI"}</span></div>
                <p>{item.content}</p>
                <footer><small>Updated {phase3Date(item.updated_at)}{item.project_id ? " · Project memory" : " · Global memory"}</small><button className="forget-button" onClick={() => props.onForgetMemory(item.id)}>Forget</button></footer>
              </article>
            ))}
            {!visibleMemory.length && <div className="empty-state compact"><div className="empty-symbol">✦</div><h2>No matching memory</h2><p>Memory created here persists on the Hermes WebUI data volume.</p></div>}
          </div>
        </section>
      )}

      {view === "goals" && (
        <section className="panel wide-panel">
          <div className="panel-heading"><h2>{selectedProjectId ? "Project goals" : "Goals"}</h2><span>{visibleGoals.length}</span></div>
          <form className="inline-form" onSubmit={props.onCreateGoal}>
            <input value={newGoalTitle} onChange={(event) => props.setNewGoalTitle(event.target.value)} placeholder={selectedProjectId ? "New project goal" : "New goal"} aria-label="New goal title" />
            <button disabled={!newGoalTitle.trim()}>Add goal</button>
          </form>
          <div className="goal-list">
            {visibleGoals.map((goal) => {
              const goalTasks = visibleTasks.filter((task) => task.goal_id === goal.id);
              return (
                <article className="goal-card" key={goal.id}>
                  <div className="goal-header"><div><span className={`status-badge ${goal.status.toLowerCase()}`}>{goal.status}</span><h3>{goal.title}</h3></div><strong>{goal.progress ?? 0}%</strong></div>
                  {goal.description && <p className="detail-copy">{goal.description}</p>}
                  <div className="progress-track"><span style={{ width: `${goal.progress ?? 0}%` }} /></div>
                  <div className="goal-meta">{goal.completed_task_count ?? 0} / {goal.task_count ?? 0} tasks completed</div>
                  <div className="task-graph">
                    {goalTasks.map((task) => (
                      <div className={`task-node ${task.status.toLowerCase()}`} key={task.id}>
                        <div className="task-node-main"><span className="task-marker">{task.status === "COMPLETED" ? "✓" : task.status === "READY" ? "●" : "○"}</span><div><strong>{task.title}</strong><small>{task.status}{task.dependencies?.length ? ` · waits for ${task.dependencies.length}` : ""}</small></div></div>
                        {task.status === "READY" || task.status === "RUNNING" ? <button className="small-button" onClick={() => props.onCompleteTask(task)}>Complete</button> : null}
                      </div>
                    ))}
                  </div>
                  <form className="task-create" onSubmit={(event) => props.onCreateTask(event, goal.id)}>
                    <input value={newTaskTitle} onChange={(event) => props.setNewTaskTitle(event.target.value)} placeholder="Add task to this graph" aria-label={`Task for ${goal.title}`} />
                    <button disabled={!newTaskTitle.trim()}>＋</button>
                  </form>
                </article>
              );
            })}
            {!visibleGoals.length && <div className="empty-state compact"><div className="empty-symbol">✦</div><h2>No goals yet</h2><p>Goals become useful when their task graph records real progress.</p></div>}
          </div>
        </section>
      )}

      {view === "tasks" && (
        <section className="panel wide-panel">
          <div className="panel-heading"><h2>{selectedProjectId ? "Project tasks" : "Tasks"}</h2><span>{visibleTasks.length}</span></div>
          <form className="inline-form" onSubmit={(event) => props.onCreateTask(event)}>
            <input value={newTaskTitle} onChange={(event) => props.setNewTaskTitle(event.target.value)} placeholder={selectedProjectId ? "New project task" : "New task"} aria-label="New task title" />
            <button disabled={!newTaskTitle.trim()}>Add task</button>
          </form>
          <div className="task-list">
            {visibleTasks.map((task) => (
              <article className={`task-node ${task.status.toLowerCase()}`} key={task.id}>
                <div className="task-node-main">
                  <span className="task-marker">{task.status === "COMPLETED" ? "✓" : task.status === "READY" ? "●" : "○"}</span>
                  <div><strong>{task.title}</strong><small>{task.status}{task.dependencies?.length ? ` · waits for ${task.dependencies.length}` : ""}</small></div>
                </div>
                <div className="task-actions">
                  {task.status === "READY" && <button className="small-button" onClick={() => props.onStartTask(task)}>Start</button>}
                  {task.status === "RUNNING" && <button className="small-button" onClick={() => props.onCompleteTask(task)}>Complete</button>}
                </div>
              </article>
            ))}
            {!visibleTasks.length && <div className="empty-state compact"><div className="empty-symbol">⌁</div><h2>No tasks yet</h2><p>Create a task here or add one to a goal in the task graph.</p></div>}
          </div>
        </section>
      )}
    </section>
  );
}

type SettingsPanelProps = {
  settings: WebUISettings | null;
  loading: boolean;
  saving: boolean;
  error: string | null;
  onToggle: (key: "show_cli_sessions" | "show_claude_code_sessions", value: boolean) => void;
};

function SettingsPanel({ settings, loading, saving, error, onToggle }: SettingsPanelProps) {
  return (
    <section className="phase3-shell">
      <header className="workspace-header">
        <div>
          <span className="eyebrow">HERMES WORKSPACE</span>
          <h1>Settings</h1>
          <p className="muted">Control what the existing WebUI shows. Provider credentials stay on the server.</p>
        </div>
        {(loading || saving) && <span className="tool-status">{saving ? "Saving…" : "Loading…"}</span>}
      </header>
      {error && <div className="inline-error">{error}</div>}
      <section className="panel settings-panel">
        {!settings ? (
          <div className="empty-state compact"><div className="empty-symbol">⚙</div><h2>Settings unavailable</h2><p>Hermes could not load the persisted WebUI settings.</p></div>
        ) : (
          <>
            <div className="settings-heading"><div><span className="eyebrow">WEBUI</span><h2>{settings.bot_name || "Hermes"}</h2></div><span className="settings-version">{settings.webui_version || "adapter"}</span></div>
            <label className="setting-row">
              <span><strong>Show CLI sessions</strong><small>Include CLI-created sessions in the conversation list.</small></span>
              <input type="checkbox" checked={settings.show_cli_sessions} onChange={(event) => onToggle("show_cli_sessions", event.target.checked)} />
            </label>
            <label className="setting-row">
              <span><strong>Show Claude Code sessions</strong><small>Include Claude Code sessions when the backend provides them.</small></span>
              <input type="checkbox" checked={settings.show_claude_code_sessions} onChange={(event) => onToggle("show_claude_code_sessions", event.target.checked)} />
            </label>
            <div className="setting-note"><span>Default model</span><strong>{settings.default_model || "Server default"}</strong></div>
            <div className="setting-note"><span>Provider</span><strong>{settings.default_model_provider || "omniroute"}</strong></div>
          </>
        )}
      </section>
    </section>
  );
}

function toChatItems(session: SessionDetail | null): ChatItem[] {
  return (session?.messages ?? [])
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message, index) => ({
      id: message.id ?? `message-${index}`,
      role: message.role as "user" | "assistant",
      content: message.content ?? "",
      reasoning: message.reasoning?.map((item) => item.text ?? "").join("") || undefined,
    }));
}

export function App() {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSession, setActiveSession] = useState<SessionDetail | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamId, setStreamId] = useState<string | null>(null);
  const [streamText, setStreamText] = useState("");
  const [thinking, setThinking] = useState("");
  const [toolCount, setToolCount] = useState(0);
  const [tools, setTools] = useState<ToolItem[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [attachments, setAttachments] = useState<File[]>([]);
  const [reconnecting, setReconnecting] = useState(false);
  const [lastSeq, setLastSeq] = useState(0);
  const [view, setView] = useState<WorkspaceView>("chat");
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [projectDetail, setProjectDetail] = useState<(Project & { sessions?: SessionSummary[]; files?: UploadedFile[]; memory?: MemoryRecord[]; goals?: Goal[]; tasks?: Task[] }) | null>(null);
  const [memory, setMemory] = useState<MemoryRecord[]>([]);
  const [memoryQuery, setMemoryQuery] = useState("");
  const [goals, setGoals] = useState<Goal[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [settings, setSettings] = useState<WebUISettings | null>(null);
  const [newProjectName, setNewProjectName] = useState("");
  const [newMemoryContent, setNewMemoryContent] = useState("");
  const [newGoalTitle, setNewGoalTitle] = useState("");
  const [newTaskTitle, setNewTaskTitle] = useState("");
  const [phase3Loading, setPhase3Loading] = useState(false);
  const [phase3Error, setPhase3Error] = useState<string | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const sourceRef = useRef<EventSource | null>(null);
  const streamIdRef = useRef<string | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const lastSeqRef = useRef(0);

  const refreshSessions = useCallback(async () => {
    const result = await api.sessions();
    setSessions(result.sessions ?? []);
    if (!selectedId && result.sessions?.[0]) {
      setSelectedId(result.sessions[0].id);
    }
  }, [selectedId]);

  const refreshPhase3 = useCallback(async () => {
    setPhase3Loading(true);
    try {
      const [projectResult, memoryResult, goalResult, taskResult] = await Promise.all([
        api.projects(),
        api.memory(memoryQuery),
        api.goals(),
        api.tasks(),
      ]);
      setProjects(projectResult.projects ?? []);
      setMemory(memoryResult.memory ?? []);
      setGoals(goalResult.goals ?? []);
      setTasks(taskResult.tasks ?? []);
      setPhase3Error(null);
    } catch (cause) {
      setPhase3Error(cause instanceof Error ? cause.message : "Unable to load Phase 3 data");
    } finally {
      setPhase3Loading(false);
    }
  }, [memoryQuery]);

  const loadSettings = useCallback(async () => {
    setSettingsLoading(true);
    try {
      setSettings(await api.settings());
      setSettingsError(null);
    } catch (cause) {
      setSettingsError(cause instanceof Error ? cause.message : "Unable to load settings");
    } finally {
      setSettingsLoading(false);
    }
  }, []);

  const loadSession = useCallback(async (sessionId: string) => {
    const result = await api.session(sessionId);
    setActiveSession(result.session);
    setSelectedId(sessionId);
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const status = await api.authStatus();
        setAuth(status);
        if (!status.logged_in) return;
        await refreshSessions();
        await refreshPhase3();
        await loadSettings();
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Unable to connect");
      } finally {
        setLoading(false);
      }
    })();
  }, [loadSettings, refreshPhase3, refreshSessions]);

  useEffect(() => {
    if (selectedId) void loadSession(selectedId);
  }, [selectedId, loadSession]);

  useEffect(() => () => {
    sourceRef.current?.close();
    if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current);
  }, []);

  const messages = useMemo(() => toChatItems(activeSession), [activeSession]);

  async function submitLogin(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.login(password);
      const status = await api.authStatus();
      setAuth(status);
      await refreshSessions();
      setPassword("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  async function createSession(projectId?: string | null) {
    setError(null);
    try {
      const result = await api.createSession(projectId);
      setSessions((current) => [result.session, ...current]);
      await loadSession(result.session.id);
      if (projectId) {
        await refreshPhase3();
        await openProject(projectId);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to create session");
    }
  }

  async function openProject(projectId: string) {
    setSelectedProjectId(projectId);
    setView("projects");
    try {
      const result = await api.project(projectId);
      setProjectDetail(result.project);
    } catch (cause) {
      setPhase3Error(cause instanceof Error ? cause.message : "Unable to load project");
    }
  }

  async function createProject(event: FormEvent) {
    event.preventDefault();
    if (!newProjectName.trim()) return;
    try {
      const result = await api.createProject({ name: newProjectName.trim() });
      setNewProjectName("");
      await refreshPhase3();
      await openProject(result.project.project_id);
    } catch (cause) {
      setPhase3Error(cause instanceof Error ? cause.message : "Unable to create project");
    }
  }

  async function createMemory(event: FormEvent) {
    event.preventDefault();
    if (!newMemoryContent.trim()) return;
    try {
      await api.createMemory({
        content: newMemoryContent.trim(),
        project_id: view === "projects" ? selectedProjectId : undefined,
      });
      setNewMemoryContent("");
      await refreshPhase3();
      if (selectedProjectId) await openProject(selectedProjectId);
    } catch (cause) {
      setPhase3Error(cause instanceof Error ? cause.message : "Unable to save memory");
    }
  }

  async function createGoal(event: FormEvent) {
    event.preventDefault();
    if (!newGoalTitle.trim()) return;
    try {
      await api.createGoal({ title: newGoalTitle.trim(), project_id: selectedProjectId });
      setNewGoalTitle("");
      await refreshPhase3();
      if (selectedProjectId) await openProject(selectedProjectId);
    } catch (cause) {
      setPhase3Error(cause instanceof Error ? cause.message : "Unable to create goal");
    }
  }

  async function createTask(event: FormEvent, goalId?: string) {
    event.preventDefault();
    if (!newTaskTitle.trim()) return;
    try {
      await api.createTask({ title: newTaskTitle.trim(), goal_id: goalId, project_id: selectedProjectId ?? undefined });
      setNewTaskTitle("");
      await refreshPhase3();
      if (selectedProjectId) await openProject(selectedProjectId);
    } catch (cause) {
      setPhase3Error(cause instanceof Error ? cause.message : "Unable to create task");
    }
  }

  async function forgetMemory(memoryId: string) {
    try {
      await api.deleteMemory(memoryId);
      await refreshPhase3();
      if (selectedProjectId) await openProject(selectedProjectId);
    } catch (cause) {
      setPhase3Error(cause instanceof Error ? cause.message : "Unable to forget memory");
    }
  }

  async function completeTask(task: Task) {
    try {
      await api.updateTask(task.id, { status: "COMPLETED" });
      await refreshPhase3();
      if (selectedProjectId) await openProject(selectedProjectId);
    } catch (cause) {
      setPhase3Error(cause instanceof Error ? cause.message : "Unable to update task");
    }
  }

  async function startTask(task: Task) {
    try {
      await api.startTask(task.id);
      await refreshPhase3();
      if (selectedProjectId) await openProject(selectedProjectId);
    } catch (cause) {
      setPhase3Error(cause instanceof Error ? cause.message : "Unable to start task");
    }
  }

  async function toggleSetting(key: "show_cli_sessions" | "show_claude_code_sessions", value: boolean) {
    if (!settings) return;
    setSettingsSaving(true);
    setSettingsError(null);
    try {
      setSettings(await api.updateSettings({ [key]: value }));
    } catch (cause) {
      setSettingsError(cause instanceof Error ? cause.message : "Unable to save settings");
    } finally {
      setSettingsSaving(false);
    }
  }

  function handleStreamEvent(event: StreamEvent) {
    setLastSeq((current) => Math.max(current, event.seq ?? 0));
    if (event.seq) lastSeqRef.current = Math.max(lastSeqRef.current, event.seq);
    if (event.event === "token") {
      setStreamText((current) => current + String(event.data.text ?? ""));
    } else if (event.event === "reasoning") {
      setThinking((current) => current + String(event.data.text ?? ""));
    } else if (event.event === "tool_call") {
      setToolCount((current) => current + 1);
      const toolId = String(event.data.id ?? event.data.tool_use_id ?? `tool-${Date.now()}`);
      setTools((current) => [
        ...current,
        {
          id: toolId,
          name: String(event.data.name ?? event.data.tool ?? "Hermes tool"),
          status: "running",
          summary: String(event.data.input ?? event.data.command ?? "Working…"),
        },
      ]);
    } else if (event.event === "tool_result") {
      const toolId = String(event.data.id ?? event.data.tool_use_id ?? "");
      setTools((current) => current.map((tool) =>
        !toolId || tool.id === toolId
          ? { ...tool, status: event.data.error ? "failed" : "complete", summary: String(event.data.output ?? event.data.result ?? "Completed") }
          : tool,
      ));
      const rawArtifact = event.data.artifact ?? event.data.artifacts;
      const candidates = Array.isArray(rawArtifact) ? rawArtifact : rawArtifact ? [rawArtifact] : [];
      for (const candidate of candidates) {
        if (typeof candidate === "object" && candidate !== null) {
          const item = candidate as Record<string, unknown>;
          setArtifacts((current) => [
            ...current,
            {
              id: String(item.id ?? `artifact-${Date.now()}-${current.length}`),
              name: String(item.name ?? item.filename ?? "Generated artifact"),
              type: String(item.type ?? item.language ?? "text"),
              content: String(item.content ?? ""),
            },
          ]);
        }
      }
    } else if (event.event === "error") {
      setError(String(event.data.error ?? "Hermes returned an error"));
    } else if (event.event === "done") {
      if (selectedId) void loadSession(selectedId);
      void refreshSessions();
    } else if (event.event === "stream_end") {
      sourceRef.current?.close();
      sourceRef.current = null;
      streamIdRef.current = null;
      setStreamId(null);
      setReconnecting(false);
    }
  }

  function connectToStream(id: string, afterSeq = 0, attempt = 0) {
    sourceRef.current?.close();
    const source = openStream(
      id,
      afterSeq,
      handleStreamEvent,
      () => {
        if (streamIdRef.current !== id || attempt >= 5) {
          setError("The stream disconnected. Refresh the conversation to replay it.");
          setReconnecting(false);
          return;
        }
        setReconnecting(true);
        const delay = Math.min(1000 * 2 ** attempt, 10000);
        reconnectTimerRef.current = window.setTimeout(() => {
          connectToStream(id, lastSeqRef.current, attempt + 1);
        }, delay);
      },
    );
    sourceRef.current = source;
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || busy) return;
    setError(null);
    setBusy(true);
    setStreamText("");
    setThinking("");
    setToolCount(0);
    setTools([]);
    setArtifacts([]);
    setLastSeq(0);
    lastSeqRef.current = 0;
    try {
      let conversationId = selectedId;
      if (!conversationId) {
        const created = await api.createSession();
        conversationId = created.session.id;
        setSessions((current) => [created.session, ...current]);
        setSelectedId(conversationId);
        await loadSession(conversationId);
      }
      const uploaded: UploadedFile[] = [];
      for (const file of attachments) {
        uploaded.push(await api.upload(file, conversationId));
      }
      const result = await api.startChat(
        conversationId,
        uploaded.length
          ? `${message}\n\n[Attached files: ${uploaded.map((file) => file.filename ?? file.file_name ?? "file").join(", ")}]`
          : message,
      );
      if (!selectedId) setSelectedId(result.session_id);
      setStreamId(result.stream_id);
      streamIdRef.current = result.stream_id;
      setDraft("");
      setAttachments([]);
      connectToStream(result.stream_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to send message");
    } finally {
      setBusy(false);
    }
  }

  async function stopMessage() {
    if (!streamIdRef.current) return;
    try {
      await api.cancelChat(streamIdRef.current);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to cancel");
    }
  }

  async function logout() {
    await api.logout();
    sourceRef.current?.close();
    setAuth((current) => (current ? { ...current, logged_in: false } : current));
    setSessions([]);
    setActiveSession(null);
    setSelectedId(null);
    setProjects([]);
    setProjectDetail(null);
    setMemory([]);
    setGoals([]);
    setTasks([]);
    setSettings(null);
    setView("chat");
  }

  if (loading) return <div className="loading-screen">Starting Hermex…</div>;

  if (!auth?.logged_in) {
    return (
      <main className="login-shell">
        <section className="login-card">
          <div className="eyebrow">HERMEX</div>
          <h1>Work with Hermes.</h1>
          <p className="muted">
            The updateable web interface for your agent, sessions, tools, and
            future autonomous work.
          </p>
          <form onSubmit={submitLogin} className="login-form">
            <label htmlFor="password">Web access password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Enter password"
              autoComplete="current-password"
            />
            <button disabled={busy || !password}>{busy ? "Signing in…" : "Sign in"}</button>
          </form>
          {error && <p className="error">{error}</p>}
        </section>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">✦</div>
          <div>
            <strong>Hermex</strong>
            <span>Hermes Agent</span>
          </div>
        </div>
        <button className="new-chat" onClick={() => void createSession()}>＋ New conversation</button>
        <nav className="workspace-nav" aria-label="Hermes workspace">
          <button className={view === "chat" ? "active" : ""} onClick={() => setView("chat")}>◌ Chat</button>
          <button className={view === "projects" ? "active" : ""} onClick={() => setView("projects")}>▦ Projects <span>{projects.length}</span></button>
          <button className={view === "memory" ? "active" : ""} onClick={() => setView("memory")}>◇ Memory <span>{memory.length}</span></button>
          <button className={view === "goals" ? "active" : ""} onClick={() => setView("goals")}>⌁ Goals <span>{goals.length}</span></button>
          <button className={view === "tasks" ? "active" : ""} onClick={() => { setSelectedProjectId(null); setView("tasks"); }}>☷ Tasks <span>{tasks.length}</span></button>
          <button className={view === "settings" ? "active" : ""} onClick={() => { setSelectedProjectId(null); setView("settings"); }}>⚙ Settings</button>
        </nav>
        <div className="section-label">Conversations</div>
        <div className="session-list">
          {sessions.map((session) => (
            <button
              className={`session-item ${session.id === selectedId ? "selected" : ""}`}
              key={session.id}
              onClick={() => setSelectedId(session.id)}
            >
              <span>{session.title || "Untitled conversation"}</span>
              {session.is_streaming && <span className="live-dot" />}
            </button>
          ))}
          {!sessions.length && <p className="sidebar-empty">No conversations yet.</p>}
        </div>
        <div className="sidebar-footer">
          <button className="text-button" onClick={logout}>Sign out</button>
          <span className="version">Web App · Phase 3</span>
        </div>
      </aside>

      <main className="chat-shell">
        {view === "settings" && (
          <SettingsPanel
            settings={settings}
            loading={settingsLoading}
            saving={settingsSaving}
            error={settingsError}
            onToggle={toggleSetting}
          />
        )}
        {view !== "chat" && view !== "settings" && (
          <Phase3Panel
            view={view}
            projects={projects}
            projectDetail={projectDetail}
            selectedProjectId={selectedProjectId}
            memory={memory}
            memoryQuery={memoryQuery}
            goals={goals}
            tasks={tasks}
            loading={phase3Loading}
            error={phase3Error}
            newProjectName={newProjectName}
            newMemoryContent={newMemoryContent}
            newGoalTitle={newGoalTitle}
            newTaskTitle={newTaskTitle}
            onView={setView}
            onOpenProject={openProject}
            onCreateProjectChat={() => void createSession(selectedProjectId)}
            onCreateProject={createProject}
            onCreateMemory={createMemory}
            onCreateGoal={createGoal}
            onCreateTask={createTask}
            onForgetMemory={forgetMemory}
            onStartTask={startTask}
            onCompleteTask={completeTask}
            setMemoryQuery={setMemoryQuery}
            setNewProjectName={setNewProjectName}
            setNewMemoryContent={setNewMemoryContent}
            setNewGoalTitle={setNewGoalTitle}
            setNewTaskTitle={setNewTaskTitle}
          />
        )}
        {view === "chat" && <>
        <header className="topbar">
          <div>
            <span className="eyebrow">CONVERSATION</span>
            <h2>{activeSession?.title || "New conversation"}</h2>
          </div>
          <div className="connection-pill"><span className="status-dot" /> Connected</div>
        </header>

        <section className="message-scroll">
          {!messages.length && !streamText && (
            <div className="empty-state">
              <div className="empty-symbol">✦</div>
              <h1>What should Hermes work on?</h1>
              <p>Ask a question now. Goals, tools, artifacts, and autonomous work will grow here without an APK update.</p>
            </div>
          )}
          {messages.map((message) => (
            <article className={`message ${message.role}`} key={message.id}>
              <div className="message-role">{message.role === "user" ? "You" : "Hermes"}</div>
              <div className="message-content">{message.content}</div>
              {message.reasoning && <details className="reasoning"><summary>Reasoning</summary>{message.reasoning}</details>}
            </article>
          ))}
          {streamId && (
            <article className="message assistant live-message">
              <div className="message-role">Hermes <span className="live-label">LIVE</span></div>
              {thinking && <details className="reasoning" open><summary>Thinking</summary>{thinking}</details>}
              {reconnecting && <div className="tool-status">↻ Reconnecting and replaying missed events…</div>}
              {tools.length > 0 && (
                <div className="tool-stack">
                  {tools.map((tool) => (
                    <div className={`tool-card ${tool.status}`} key={tool.id}>
                      <span>{tool.status === "running" ? "◌" : tool.status === "complete" ? "✓" : "!"}</span>
                      <div><strong>{tool.name}</strong><small>{tool.summary}</small></div>
                    </div>
                  ))}
                </div>
              )}
              <div className="message-content">
                <MarkdownContent text={streamText || "Thinking…"} />
              </div>
            </article>
          )}
          {artifacts.length > 0 && (
            <section className="artifact-stack">
              <div className="section-label">Artifacts</div>
              {artifacts.map((artifact) => (
                <details className="artifact-card" key={artifact.id}>
                  <summary><span>▣</span><strong>{artifact.name}</strong><small>{artifact.type}</small></summary>
                  <pre><code>{artifact.content}</code></pre>
                </details>
              ))}
            </section>
          )}
          {error && <div className="inline-error">{error}</div>}
        </section>

        <form className="composer-wrap" onSubmit={sendMessage}>
          {attachments.length > 0 && (
            <div className="attachment-list">
              {attachments.map((file) => <span key={file.name}>{file.name}</span>)}
            </div>
          )}
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder="Message Hermes…"
            rows={1}
          />
          <div className="composer-actions">
            <label className="attach-button">
              ＋ Attach
              <input
                type="file"
                multiple
                onChange={(event) => setAttachments(Array.from(event.target.files ?? []))}
              />
            </label>
            <span>Shift + Enter for a new line</span>
            {streamId ? (
              <button type="button" className="stop-button" onClick={stopMessage}>Stop</button>
            ) : (
              <button type="submit" disabled={!draft.trim() || busy}>Send ↑</button>
            )}
          </div>
        </form>
        </>}
      </main>
    </div>
  );
}