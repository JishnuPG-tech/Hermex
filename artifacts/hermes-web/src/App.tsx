import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  AuthStatus,
  openStream,
  SessionDetail,
  SessionSummary,
  StreamEvent,
} from "./api";

type ChatItem = {
  id: string;
  role: "user" | "assistant";
  content: string;
  reasoning?: string;
  toolCount?: number;
};

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
  const [lastSeq, setLastSeq] = useState(0);
  const sourceRef = useRef<EventSource | null>(null);
  const streamIdRef = useRef<string | null>(null);

  const refreshSessions = useCallback(async () => {
    const result = await api.sessions();
    setSessions(result.sessions ?? []);
    if (!selectedId && result.sessions?.[0]) {
      setSelectedId(result.sessions[0].id);
    }
  }, [selectedId]);

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
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Unable to connect");
      } finally {
        setLoading(false);
      }
    })();
  }, [refreshSessions]);

  useEffect(() => {
    if (selectedId) void loadSession(selectedId);
  }, [selectedId, loadSession]);

  useEffect(() => () => sourceRef.current?.close(), []);

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

  async function createSession() {
    setError(null);
    try {
      const result = await api.createSession();
      setSessions((current) => [result.session, ...current]);
      await loadSession(result.session.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to create session");
    }
  }

  function handleStreamEvent(event: StreamEvent) {
    setLastSeq(event.seq ?? lastSeq);
    if (event.event === "token") {
      setStreamText((current) => current + String(event.data.text ?? ""));
    } else if (event.event === "reasoning") {
      setThinking((current) => current + String(event.data.text ?? ""));
    } else if (event.event === "tool_call" || event.event === "tool_result") {
      setToolCount((current) => current + 1);
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
    }
  }

  function connectToStream(id: string, afterSeq = 0) {
    sourceRef.current?.close();
    const source = openStream(
      id,
      afterSeq,
      handleStreamEvent,
      () => setError("The stream disconnected. Retrying may replay the missed events."),
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
    setLastSeq(0);
    try {
      const result = await api.startChat(selectedId, message);
      if (!selectedId) setSelectedId(result.session_id);
      setStreamId(result.stream_id);
      streamIdRef.current = result.stream_id;
      setDraft("");
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
        <button className="new-chat" onClick={createSession}>＋ New conversation</button>
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
          <span className="version">Web App · Phase 1</span>
        </div>
      </aside>

      <main className="chat-shell">
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
              {toolCount > 0 && <div className="tool-status">◌ Working with tools · {toolCount} events</div>}
              <div className="message-content">{streamText || "Thinking…"}</div>
            </article>
          )}
          {error && <div className="inline-error">{error}</div>}
        </section>

        <form className="composer-wrap" onSubmit={sendMessage}>
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
            <span>Shift + Enter for a new line</span>
            {streamId ? (
              <button type="button" className="stop-button" onClick={stopMessage}>Stop</button>
            ) : (
              <button type="submit" disabled={!draft.trim() || busy}>Send ↑</button>
            )}
          </div>
        </form>
      </main>
    </div>
  );
}