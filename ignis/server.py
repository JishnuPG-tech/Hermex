import os
import json
import re
import time
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="Ignis Obsidian Vault Server", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

VAULT_DIR = Path(os.getenv("OBSIDIAN_VAULT_DIR", "/data/obsidian/vault"))
VAULT_DIR.mkdir(parents=True, exist_ok=True)

# Ensure sample initial notes exist if empty
welcome_note = VAULT_DIR / "Welcome.md"
if not welcome_note.exists():
    welcome_note.write_text("""# 📚 Welcome to Your Obsidian Knowledge Vault!

This is your persistent memory and knowledge graph for **Hermes Agent**.

### ⚡ Features:
- **Bi-directional Links:** Connect your notes using `[[Other Note]]` syntax.
- **Autonomous Agent Memory:** Hermes automatically saves research, project tasks, and execution logs here.
- **Interactive Graph:** Click the **Graph View** button at the top to explore connections visually!
- **Markdown & Math:** Supports standard Markdown, code blocks, and KaTeX math formulas.

---
*Created by Hermes Agent Core on persistent storage (/data/obsidian/vault).*
""", encoding="utf-8")

architecture_note = VAULT_DIR / "Architecture.md"
if not architecture_note.exists():
    architecture_note.write_text("""# 🏗️ Hermes + Obsidian Architecture

See [[Welcome]] for an introduction.

- **Hermes Core:** Runs on port 8642 with dynamic tool activation.
- **OmniRoute Gateway:** Connected upstream at `jishnupg-opencode-cli.hf.space`.
- **Knowledge Store:** Markdown graph in [[Welcome]].
""", encoding="utf-8")


@app.get("/health")
@app.get("/obsidian/health")
@app.get("/health/live")
async def health():
    return {"status": "ok", "service": "ignis_obsidian_vault", "notes_count": len(list(VAULT_DIR.rglob("*.md")))}


@app.get("/", response_class=HTMLResponse)
@app.get("/vault", response_class=HTMLResponse)
async def vault_webapp():
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Obsidian Knowledge Vault - Hermes</title>
    <!-- Tailwind CSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- Marked.js for Markdown Rendering -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <!-- FontAwesome Icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        body { background-color: #0f172a; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
        .sidebar { background-color: #1e293b; border-right: 1px solid #334155; }
        .editor-pane { background-color: #0f172a; }
        .preview-pane { background-color: #1e293b; }
        .markdown-body h1 { font-size: 1.8rem; font-weight: 700; color: #38bdf8; margin-top: 1rem; margin-bottom: 0.5rem; }
        .markdown-body h2 { font-size: 1.4rem; font-weight: 600; color: #818cf8; margin-top: 0.8rem; margin-bottom: 0.4rem; }
        .markdown-body h3 { font-size: 1.2rem; font-weight: 600; color: #c084fc; margin-top: 0.6rem; margin-bottom: 0.3rem; }
        .markdown-body p { margin-bottom: 0.75rem; line-height: 1.6; color: #cbd5e1; }
        .markdown-body ul { list-style-type: disc; margin-left: 1.5rem; margin-bottom: 0.75rem; }
        .markdown-body code { background: #0f172a; color: #38bdf8; padding: 2px 6px; border-radius: 4px; font-family: monospace; }
        .markdown-body pre { background: #020617; padding: 1rem; border-radius: 8px; overflow-x: auto; margin-bottom: 1rem; border: 1px solid #1e293b; }
        .markdown-body pre code { background: transparent; padding: 0; }
        .wikilink { color: #a855f7; font-weight: 600; text-decoration: underline; cursor: pointer; }
        .wikilink:hover { color: #c084fc; }
    </style>
</head>
<body class="h-screen flex flex-col overflow-hidden">

    <!-- Top Navigation Bar -->
    <header class="h-14 bg-slate-900 border-b border-slate-800 flex items-center justify-between px-4 z-10">
        <div class="flex items-center space-x-3">
            <i class="fa-solid fa-gem text-purple-500 text-xl"></i>
            <span class="font-bold text-lg text-white">Obsidian <span class="text-purple-400">Vault</span></span>
            <span class="text-xs bg-purple-950 text-purple-300 border border-purple-800 px-2 py-0.5 rounded-full">Hermes Agent Memory</span>
        </div>
        <div class="flex items-center space-x-2">
            <button onclick="toggleGraphModal()" class="px-3 py-1.5 bg-purple-600 hover:bg-purple-500 text-white rounded-md text-sm font-medium transition flex items-center space-x-2">
                <i class="fa-solid fa-circle-nodes"></i>
                <span>Graph View</span>
            </button>
            <button onclick="createNewNotePrompt()" class="px-3 py-1.5 bg-sky-600 hover:bg-sky-500 text-white rounded-md text-sm font-medium transition flex items-center space-x-2">
                <i class="fa-solid fa-plus"></i>
                <span>New Note</span>
            </button>
            <a href="/" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-md text-sm transition flex items-center space-x-1">
                <i class="fa-solid fa-house"></i>
                <span>Dashboard</span>
            </a>
        </div>
    </header>

    <!-- Main Workspace -->
    <div class="flex-1 flex overflow-hidden">
        
        <!-- Sidebar / File Explorer -->
        <aside class="w-64 sidebar flex flex-col">
            <div class="p-3 border-b border-slate-700">
                <div class="relative">
                    <input type="text" id="searchInput" oninput="filterNotes()" placeholder="Search notes..." class="w-full bg-slate-950 border border-slate-700 rounded px-3 py-1.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-purple-500 pl-8">
                    <i class="fa-solid fa-search absolute left-2.5 top-2.5 text-slate-500 text-xs"></i>
                </div>
            </div>
            <div class="flex-1 overflow-y-auto p-2" id="notesList">
                <div class="text-xs text-slate-500 p-2">Loading notes...</div>
            </div>
            <div class="p-3 bg-slate-900/50 border-t border-slate-800 text-xs text-slate-500 flex justify-between">
                <span id="noteCount">0 notes</span>
                <span id="saveStatus" class="text-green-400 font-mono">Synced</span>
            </div>
        </aside>

        <!-- Editor & Preview Split Panes -->
        <main class="flex-1 flex flex-col md:flex-row overflow-hidden">
            
            <!-- Editor Pane -->
            <div class="flex-1 flex flex-col border-r border-slate-800">
                <div class="h-10 bg-slate-900/80 border-b border-slate-800 flex items-center justify-between px-4">
                    <input type="text" id="currentNoteTitle" class="bg-transparent text-sm font-semibold text-sky-400 focus:outline-none w-2/3" placeholder="Note Title...">
                    <div class="flex items-center space-x-2 text-xs text-slate-400">
                        <button onclick="saveCurrentNote()" class="hover:text-white"><i class="fa-solid fa-floppy-disk mr-1"></i>Save</button>
                        <button onclick="deleteCurrentNote()" class="hover:text-red-400"><i class="fa-solid fa-trash mr-1"></i>Delete</button>
                    </div>
                </div>
                <textarea id="markdownEditor" oninput="handleEditorInput()" class="flex-1 editor-pane p-4 text-slate-200 font-mono text-sm resize-none focus:outline-none placeholder-slate-600" placeholder="Type your markdown here... Use [[Note Name]] to link to other notes."></textarea>
            </div>

            <!-- Live Rendered Preview Pane -->
            <div class="flex-1 preview-pane p-6 overflow-y-auto markdown-body" id="markdownPreview">
                <div class="text-slate-500 italic">Select or create a note to start reading...</div>
            </div>

        </main>
    </div>

    <!-- Graph View Modal -->
    <div id="graphModal" class="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 hidden flex items-center justify-center p-6">
        <div class="bg-slate-900 border border-slate-700 rounded-xl w-full max-w-4xl h-[80vh] flex flex-col shadow-2xl overflow-hidden">
            <div class="p-4 border-b border-slate-800 flex justify-between items-center bg-slate-950">
                <div class="flex items-center space-x-2">
                    <i class="fa-solid fa-circle-nodes text-purple-400"></i>
                    <h3 class="font-bold text-white">Interactive Knowledge Graph View</h3>
                </div>
                <button onclick="toggleGraphModal()" class="text-slate-400 hover:text-white text-lg"><i class="fa-solid fa-xmark"></i></button>
            </div>
            <div class="flex-1 relative bg-slate-950" id="graphContainer">
                <canvas id="graphCanvas" class="w-full h-full"></canvas>
            </div>
        </div>
    </div>

    <!-- JavaScript Application Logic -->
    <script>
        let allNotes = [];
        let currentNotePath = "";
        let saveTimeout = null;

        async function loadNotes() {
            try {
                const res = await fetch('/vault/api/notes');
                const data = await res.json();
                allNotes = data.notes || [];
                renderNotesList(allNotes);
                document.getElementById('noteCount').innerText = `${allNotes.length} notes`;

                if (allNotes.length > 0 && !currentNotePath) {
                    openNote(allNotes[0].path);
                }
            } catch (err) {
                console.error("Failed to load notes", err);
            }
        }

        function renderNotesList(notes) {
            const listEl = document.getElementById('notesList');
            if (notes.length === 0) {
                listEl.innerHTML = '<div class="text-xs text-slate-500 p-2">No notes found.</div>';
                return;
            }
            listEl.innerHTML = notes.map(n => `
                <div onclick="openNote('${n.path}')" class="p-2 rounded text-sm cursor-pointer transition flex items-center justify-between mb-1 ${currentNotePath === n.path ? 'bg-purple-900/40 text-purple-300 font-medium border border-purple-800/50' : 'text-slate-300 hover:bg-slate-800'}">
                    <span class="truncate"><i class="fa-regular fa-file-lines mr-2 text-xs text-purple-400"></i>${n.name.replace(/\\.md$/, '')}</span>
                    <span class="text-[10px] text-slate-500">${(n.size / 1024).toFixed(1)}k</span>
                </div>
            `).join('');
        }

        function filterNotes() {
            const q = document.getElementById('searchInput').value.toLowerCase();
            const filtered = allNotes.filter(n => n.name.toLowerCase().includes(q));
            renderNotesList(filtered);
        }

        async function openNote(path) {
            currentNotePath = path;
            renderNotesList(allNotes);
            document.getElementById('currentNoteTitle').value = path.replace(/\.md$/, '');
            try {
                const res = await fetch(`/vault/api/note?path=${encodeURIComponent(path)}`);
                const data = await res.json();
                const content = data.content || "";
                document.getElementById('markdownEditor').value = content;
                renderMarkdown(content);
            } catch (e) {
                console.error("Error reading note", e);
            }
        }

        function handleEditorInput() {
            const content = document.getElementById('markdownEditor').value;
            renderMarkdown(content);
            document.getElementById('saveStatus').innerText = "Unsaved...";
            document.getElementById('saveStatus').className = "text-yellow-400 font-mono";

            clearTimeout(saveTimeout);
            saveTimeout = setTimeout(saveCurrentNote, 1000);
        }

        function renderMarkdown(md) {
            // Convert [[Wikilinks]] to clickable badges
            const processed = md.replace(/\[\[(.*?)\]\]/g, (match, p1) => {
                return `<span class="wikilink" onclick="openOrCreateWikiLink('${p1}')">${p1}</span>`;
            });
            document.getElementById('markdownPreview').innerHTML = marked.parse(processed);
        }

        async function saveCurrentNote() {
            if (!currentNotePath) return;
            const content = document.getElementById('markdownEditor').value;
            const title = document.getElementById('currentNoteTitle').value.trim();
            const targetPath = title.endsWith('.md') ? title : `${title}.md`;

            try {
                await fetch('/vault/api/note', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: targetPath, content: content })
                });
                document.getElementById('saveStatus').innerText = "Synced";
                document.getElementById('saveStatus').className = "text-green-400 font-mono";
                loadNotes();
            } catch (err) {
                document.getElementById('saveStatus').innerText = "Save error";
                document.getElementById('saveStatus').className = "text-red-400 font-mono";
            }
        }

        async function createNewNotePrompt() {
            const title = prompt("Enter new note title:");
            if (!title) return;
            const filename = title.endsWith('.md') ? title : `${title}.md`;
            await fetch('/vault/api/note', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: filename, content: `# ${title}\n\nStart writing your note here...` })
            });
            await loadNotes();
            openNote(filename);
        }

        async function deleteCurrentNote() {
            if (!currentNotePath || !confirm(`Delete note '${currentNotePath}'?`)) return;
            await fetch(`/vault/api/note?path=${encodeURIComponent(currentNotePath)}`, { method: 'DELETE' });
            currentNotePath = "";
            document.getElementById('markdownEditor').value = "";
            document.getElementById('markdownPreview').innerHTML = "";
            await loadNotes();
        }

        function openOrCreateWikiLink(linkName) {
            const target = `${linkName}.md`;
            const found = allNotes.find(n => n.name.toLowerCase() === target.toLowerCase() || n.name.toLowerCase() === linkName.toLowerCase());
            if (found) {
                openNote(found.path);
            } else {
                if (confirm(`Note '${linkName}' does not exist. Create it?`)) {
                    fetch('/vault/api/note', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ path: target, content: `# ${linkName}\n\nLinked from [[${currentNotePath.replace(/\.md$/, '')}]]` })
                    }).then(() => {
                        loadNotes().then(() => openNote(target));
                    });
                }
            }
        }

        // Graph View Canvas Simulation
        function toggleGraphModal() {
            const modal = document.getElementById('graphModal');
            modal.classList.toggle('hidden');
            if (!modal.classList.contains('hidden')) {
                drawGraph();
            }
        }

        async function drawGraph() {
            const canvas = document.getElementById('graphCanvas');
            const ctx = canvas.getContext('2d');
            canvas.width = canvas.parentElement.clientWidth;
            canvas.height = canvas.parentElement.clientHeight;

            // Fetch graph connections
            const res = await fetch('/vault/api/graph');
            const graphData = await res.json();
            const nodes = graphData.nodes || [];
            const links = graphData.links || [];

            // Random initial placement
            nodes.forEach((n, i) => {
                n.x = canvas.width / 2 + (Math.cos(i) * 120) + (Math.random() * 40);
                n.y = canvas.height / 2 + (Math.sin(i) * 120) + (Math.random() * 40);
            });

            ctx.clearRect(0, 0, canvas.width, canvas.height);

            // Draw Links
            ctx.strokeStyle = "#475569";
            ctx.lineWidth = 1.5;
            links.forEach(l => {
                const src = nodes.find(n => n.id === l.source);
                const tgt = nodes.find(n => n.id === l.target);
                if (src && tgt) {
                    ctx.beginPath();
                    ctx.moveTo(src.x, src.y);
                    ctx.lineTo(tgt.x, tgt.y);
                    ctx.stroke();
                }
            });

            // Draw Nodes
            nodes.forEach(n => {
                ctx.beginPath();
                ctx.arc(n.x, n.y, 8, 0, 2 * Math.PI);
                ctx.fillStyle = n.id === currentNotePath.replace(/\.md$/, '') ? "#38bdf8" : "#a855f7";
                ctx.fill();
                ctx.strokeStyle = "#ffffff";
                ctx.lineWidth = 1;
                ctx.stroke();

                ctx.fillStyle = "#cbd5e1";
                ctx.font = "12px sans-serif";
                ctx.fillText(n.id, n.x + 12, n.y + 4);
            });
        }

        window.onload = loadNotes;
    </script>
</body>
</html>
"""

# REST API endpoints for Obsidian WebApp
@app.get("/api/notes")
async def api_get_notes():
    notes = []
    for p in VAULT_DIR.rglob("*.md"):
        notes.append({
            "name": p.name,
            "path": str(p.relative_to(VAULT_DIR)).replace("\\", "/"),
            "size": p.stat().st_size,
            "modified": p.stat().st_mtime
        })
    return {"notes": notes}

@app.get("/api/note")
async def api_get_note(path: str):
    target = VAULT_DIR / path
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Note not found")
    return {"path": path, "content": target.read_text(encoding="utf-8", errors="ignore")}

@app.post("/api/note")
async def api_save_note(request: Request):
    data = await request.json()
    rel_path = data.get("path", "").strip()
    content = data.get("content", "")
    if not rel_path:
        raise HTTPException(status_code=400, detail="Invalid path")
    target = VAULT_DIR / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"status": "saved", "path": rel_path}

@app.delete("/api/note")
async def api_delete_note(path: str):
    target = VAULT_DIR / path
    if target.exists() and target.is_file():
        target.unlink()
        return {"status": "deleted"}
    raise HTTPException(status_code=404, detail="Note not found")

@app.get("/api/graph")
async def api_get_graph():
    nodes = []
    links = []
    note_map = {}
    for p in VAULT_DIR.rglob("*.md"):
        note_id = p.stem
        nodes.append({"id": note_id, "path": str(p.relative_to(VAULT_DIR)).replace("\\", "/")})
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            # Extract [[wikilinks]]
            targets = re.findall(r"\[\[([^\]]+)\]\]", content)
            for t in targets:
                links.append({"source": note_id, "target": t.strip()})
        except Exception:
            pass
    return {"nodes": nodes, "links": links}


@app.get("/vault/api/notes")
async def alias_notes():
    return await api_get_notes()

@app.get("/vault/api/note")
async def alias_get_note(path: str):
    return await api_get_note(path)

@app.post("/vault/api/note")
async def alias_post_note(request: Request):
    return await api_save_note(request)

@app.delete("/vault/api/note")
async def alias_del_note(path: str):
    return await api_delete_note(path)

@app.get("/vault/api/graph")
async def alias_graph():
    return await api_get_graph()

@app.get("/api/vaults")
@app.get("/vault/api/vaults")
async def api_get_vaults():
    return [
        {
            "name": "Hermes-Vault",
            "path": str(VAULT_DIR),
            "noteCount": len(list(VAULT_DIR.rglob("*.md")))
        }
    ]

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)
