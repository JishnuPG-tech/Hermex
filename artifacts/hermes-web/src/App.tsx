import { FormEvent, ReactElement, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  AuthStatus,
  openStream,
  SessionDetail,
  SessionSummary,
  StreamEvent,
  UploadedFile,
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
      </main>
    </div>
  );
}