import os
from pathlib import Path
from hermes_core.tools.registry import registry

VAULT_DIR = Path(os.getenv("OBSIDIAN_VAULT_DIR", "/data/obsidian/vault"))
VAULT_DIR.mkdir(parents=True, exist_ok=True)

@registry.register(
    name="vault_search_notes",
    description="Search notes and knowledge documents in the Obsidian Vault.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search keyword or phrase"}
        },
        "required": ["query"]
    },
    category="vault"
)
def vault_search_notes(query: str) -> str:
    matches = []
    q = query.lower()
    for p in VAULT_DIR.rglob("*.md"):
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            if q in p.name.lower() or q in content.lower():
                matches.append(f"- {p.relative_to(VAULT_DIR)}: {content[:150]}...")
        except Exception:
            pass
    if not matches:
        return f"No notes found matching '{query}' in Obsidian vault."
    return "\n".join(matches[:10])

@registry.register(
    name="vault_write_note",
    description="Create or update a markdown note in the Obsidian Vault.",
    parameters={
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "Relative filename (e.g. 'Projects/AI.md')"},
            "content": {"type": "string", "description": "Markdown content for the note"},
            "mode": {"type": "string", "enum": ["overwrite", "append"], "description": "Write mode (default: overwrite)"}
        },
        "required": ["filename", "content"]
    },
    category="vault"
)
def vault_write_note(filename: str, content: str, mode: str = "overwrite") -> str:
    target = VAULT_DIR / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "append" and target.exists():
        existing = target.read_text(encoding="utf-8", errors="ignore")
        target.write_text(existing + "\n\n" + content, encoding="utf-8")
    else:
        target.write_text(content, encoding="utf-8")
    return f"Successfully saved note '{filename}' to Obsidian Vault."
