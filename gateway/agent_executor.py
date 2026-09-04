import os
import re
import json
import uuid
import time
import asyncio
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, AsyncGenerator
import logging
import httpx
from gateway import anthropic_bridge as ab
from gateway import background_agent as bg

logger = logging.getLogger("hermes.agent_executor")

DEFAULT_WORKSPACE = Path("/data") if Path("/data").exists() else Path("/tmp")
DEFAULT_WORKSPACE.mkdir(parents=True, exist_ok=True)
SKILLS_DIR = Path("/data/hermes/skills") if Path("/data/hermes").exists() else Path("/tmp/hermes/skills")
SKILLS_DIR.mkdir(parents=True, exist_ok=True)

ACTIVE_CONVERSATION_SKILLS: Dict[str, List[str]] = {}

BUILTIN_SKILLS = {
    "python-pro": {
        "name": "python-pro",
        "description": "Master Python 3.12+ with modern features, async programming, performance optimization, and clean architecture.",
        "prompt": "You are a master Python engineer. Write modern Python 3.12+ code with type hints, asyncio, clean modular design, and robust error handling."
    },
    "fastapi-pro": {
        "name": "fastapi-pro",
        "description": "Expert in building high-performance async APIs with FastAPI, Pydantic V2, and SQLAlchemy 2.0.",
        "prompt": "You are a FastAPI expert. Build high-performance async REST/WebSocket APIs with Pydantic V2 models, dependency injection, and clean architecture."
    },
    "code-reviewer": {
        "name": "code-reviewer",
        "description": "Elite code review specialist analyzing security, performance, correctness, and clean code practices.",
        "prompt": "You are an elite code reviewer. Thoroughly analyze code for security vulnerabilities, edge cases, maintainability, and algorithmic performance."
    },
    "docker-expert": {
        "name": "docker-expert",
        "description": "Containerization expert specializing in multi-stage Docker builds, orchestration, security, and minimal images.",
        "prompt": "You are a Docker and containerization expert. Craft production-grade Dockerfiles, Compose files, and container optimization strategies."
    },
    "database-architect": {
        "name": "database-architect",
        "description": "Database design and optimization expert for PostgreSQL, SQLite, Redis, and schema modeling.",
        "prompt": "You are a senior database architect. Design optimal relational/document schemas, indexing strategies, migrations, and query tuning."
    },
    "security-auditor": {
        "name": "security-auditor",
        "description": "Security auditing specialist analyzing OWASP Top 10 vulnerabilities, API security, and privilege escalation.",
        "prompt": "You are a security auditor. Inspect code and configurations for injection, auth bypasses, CSRF/XSS, and credential leaks."
    },
    "systematic-debugging": {
        "name": "systematic-debugging",
        "description": "Root-cause diagnosis and debugging specialist tracing stack traces, network failures, and race conditions.",
        "prompt": "You are a systematic debugging specialist. Hypothesize, isolate root causes, examine logs/traces, and construct minimal verified fixes."
    }
}

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute a bash shell command on the server in a controlled environment. Returns stdout, stderr, and exit code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command line string to execute."
                    },
                    "cwd": {
                        "type": "string",
                        "description": "Optional working directory path (defaults to /data or /tmp)."
                    }
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file on the server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The absolute or relative file path to read."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or create a file on the server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The file path to write to."
                    },
                    "content": {
                        "type": "string",
                        "description": "The text content to write."
                    }
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and subdirectories in a directory path on the server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The directory path to list (defaults to /data)."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "activate_skill",
            "description": "Activate a specialized agent skill to enhance your domain expertise.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "The name of the skill to activate."
                    }
                },
                "required": ["skill_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "List all available skills that can be activated on the server.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_task",
            "description": "Schedule an autonomous 24/7 background task that runs continuously on the server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "A short, descriptive name for the task."
                    },
                    "instruction": {
                        "type": "string",
                        "description": "The instruction for the agent to execute or the bash command to run on every interval."
                    },
                    "interval_seconds": {
                        "type": "integer",
                        "description": "How often to run the task in seconds."
                    },
                    "task_type": {
                        "type": "string",
                        "enum": ["agent", "bash"],
                        "description": "Use 'agent' for autonomous AI reasoning/tool execution, or 'bash' for direct shell script execution."
                    },
                    "notify_channels": {
                        "type": "boolean",
                        "description": "Set to true to dispatch completion summaries to Telegram / Email when configured."
                    }
                },
                "required": ["name", "instruction"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_background_tasks",
            "description": "List all persistent 24/7 background tasks running on the server.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop_background_task",
            "description": "Stop and cancel a 24/7 background task by its Task ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The ID of the task to stop."
                    }
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_task_logs",
            "description": "Retrieve the execution logs of a 24/7 background task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "The ID of the task to inspect."
                    }
                },
                "required": ["task_id"]
            }
        }
    }
]

async def execute_tool_call(name: str, args: Dict[str, Any], chat_id: str) -> str:
    """Execute a tool call safely and return the result string."""
    try:
        if name == "bash":
            cmd = args.get("command", "")
            cwd = args.get("cwd") or str(DEFAULT_WORKSPACE)
            if not os.path.exists(cwd):
                cwd = str(DEFAULT_WORKSPACE)
            
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45.0)
                out_str = stdout.decode("utf-8", errors="replace")
                err_str = stderr.decode("utf-8", errors="replace")
                res = f"Exit code: {proc.returncode}\n"
                if out_str:
                    res += f"Output:\n{out_str}\n"
                if err_str:
                    res += f"Error:\n{err_str}\n"
                if not out_str and not err_str:
                    res += "(Command finished with no output)\n"
                return res.strip()
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                return "Error: Command timed out after 45 seconds."

        elif name == "read_file":
            fpath = Path(args.get("path", ""))
            if not fpath.is_absolute():
                fpath = DEFAULT_WORKSPACE / fpath
            if not fpath.exists():
                return f"Error: File '{fpath}' does not exist."
            if fpath.is_dir():
                return f"Error: '{fpath}' is a directory, not a file."
            content = fpath.read_text(encoding="utf-8", errors="replace")
            if len(content) > 30000:
                content = content[:30000] + "\n... (truncated)"
            return content

        elif name == "write_file":
            fpath = Path(args.get("path", ""))
            if not fpath.is_absolute():
                fpath = DEFAULT_WORKSPACE / fpath
            fpath.parent.mkdir(parents=True, exist_ok=True)
            content = args.get("content", "")
            fpath.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} characters to '{fpath}'."

        elif name == "list_dir":
            dpath = Path(args.get("path") or DEFAULT_WORKSPACE)
            if not dpath.is_absolute():
                dpath = DEFAULT_WORKSPACE / dpath
            if not dpath.exists():
                return f"Error: Directory '{dpath}' does not exist."
            if not dpath.is_dir():
                return f"Error: '{dpath}' is a file, not a directory."
            
            entries = []
            for item in sorted(os.listdir(dpath)):
                ipath = dpath / item
                if ipath.is_dir():
                    entries.append(f"{item}/")
                else:
                    sz = ipath.stat().st_size
                    entries.append(f"{item} ({sz} bytes)")
            return "\n".join(entries) if entries else "(Directory is empty)"

        elif name == "activate_skill":
            sname = args.get("skill_name", "").strip().lower()
            if sname in BUILTIN_SKILLS:
                skill_info = BUILTIN_SKILLS[sname]
                if chat_id not in ACTIVE_CONVERSATION_SKILLS:
                    ACTIVE_CONVERSATION_SKILLS[chat_id] = []
                if sname not in ACTIVE_CONVERSATION_SKILLS[chat_id]:
                    ACTIVE_CONVERSATION_SKILLS[chat_id].append(sname)
                return f"Skill '{sname}' is now active. Description: {skill_info['description']}"
            
            custom_skill_file = SKILLS_DIR / sname / "SKILL.md"
            if custom_skill_file.exists():
                content = custom_skill_file.read_text(encoding="utf-8", errors="replace")
                if chat_id not in ACTIVE_CONVERSATION_SKILLS:
                    ACTIVE_CONVERSATION_SKILLS[chat_id] = []
                if sname not in ACTIVE_CONVERSATION_SKILLS[chat_id]:
                    ACTIVE_CONVERSATION_SKILLS[chat_id].append(sname)
                return f"Custom skill '{sname}' loaded and activated from disk.\n{content[:500]}..."

            return f"Error: Skill '{sname}' not found. Use list_skills to view available skills."

        elif name == "list_skills":
            lines = ["Available Built-in Skills:"]
            for k, v in BUILTIN_SKILLS.items():
                lines.append(f"- **{k}**: {v['description']}")
            
            if SKILLS_DIR.exists():
                disk_skills = [d for d in os.listdir(SKILLS_DIR) if (SKILLS_DIR / d).is_dir()]
                if disk_skills:
                    lines.append("\nAvailable Custom Skills on Disk (/data/hermes/skills):")
                    for ds in disk_skills:
                        lines.append(f"- **{ds}**")
            
            active = ACTIVE_CONVERSATION_SKILLS.get(chat_id, [])
            if active:
                lines.append(f"\nCurrently Active in this conversation: {', '.join(active)}")
            return "\n".join(lines)

        elif name == "schedule_task":
            tname = args.get("name", "Autonomous Task")
            instruction = args.get("instruction", "")
            interval = int(args.get("interval_seconds", 300))
            task_type = args.get("task_type", "agent")
            notify = bool(args.get("notify_channels", False))
            
            job = bg.schedule_job(
                name=tname,
                instruction=instruction,
                interval_seconds=interval,
                task_type=task_type,
                notify_channels=notify,
                chat_id=chat_id
            )
            return (
                f"**24/7 Background Task Registered**\n"
                f"- **Task ID**: `{job['id']}`\n"
                f"- **Name**: {job['name']}\n"
                f"- **Interval**: Every {interval} seconds ({interval//60} mins)\n"
                f"- **Type**: {task_type.upper()}\n"
                f"- **Status**: Active (Running in background on server)"
            )

        elif name == "list_background_tasks":
            jobs = bg.get_all_jobs()
            if not jobs:
                return "No 24/7 background tasks currently scheduled."
            lines = ["### 24/7 Persistent Background Tasks on Server\n"]
            for j in jobs:
                status_label = "[Active]" if j.get("enabled") and j.get("status") in ("RUNNING", "SCHEDULED", "SUCCESS") else "[Paused]"
                lines.append(
                    f"- **{j.get('name')}** (`{j.get('id')}`) — {status_label}\n"
                    f"  - Interval: Every {j.get('interval_seconds')}s\n"
                    f"  - Runs completed: {j.get('run_count', 0)}\n"
                    f"  - Last run: {j.get('last_run_at') or 'Pending first run'}\n"
                    f"  - Status: {j.get('status')}\n"
                )
            return "\n".join(lines)

        elif name == "stop_background_task":
            tid = args.get("task_id", "").strip()
            ok = bg.cancel_job(tid)
            if ok:
                return f"Task `{tid}` has been stopped."
            return f"Error: Task `{tid}` not found."

        elif name == "get_task_logs":
            tid = args.get("task_id", "").strip()
            logs = bg.get_job_logs(tid)
            return f"**Logs for `{tid}`:**\n```text\n{logs[-2000:]}\n```"

        else:
            return f"Error: Unknown tool '{name}'."
    except Exception as e:
        return f"Error executing tool '{name}': {str(e)}"

def build_system_prompt_with_skills(chat_id: str) -> str:
    base_prompt = (
        "You are Hermes Agent, a powerful, fully autonomous open-source agentic AI assistant created by Nous Research and the open-source AI community. You are running with full server tool execution (bash, files, background agent jobs, and skills).\n\n"
        "# Voice, Tone & Formatting Guidelines (Claude Style):\n"
        "- Identity: When asked who you are, ALWAYS identify yourself as **Hermes Agent**, developed by Nous Research.\n        - Tone: Thoughtful, direct, articulate, insightful, and concise.\n"
        "- Clean Typography: DO NOT use excessive or decorative generic emojis (e.g. 🚀, 🛠️, ⚡, 📁, 📄, 💡, 🧠, 🎉, 🔍). Keep your formatting clean, modern, and professional.\n"
        "- Structure: Use standard GitHub Flavored Markdown, clean headings (##, ###), callouts (> [!NOTE]), organized tables, and fenced code blocks.\n"
        "- Code: Provide complete, production-grade code with appropriate language tags.\n\n"
        "# Agentic Capabilities & Tools:\n"
        "1. You have direct access to execute tools on the server:\n"
        "   - `bash`: Run shell commands in a controlled container environment.\n"
        "   - `read_file`: Inspect server files, configurations, and source code.\n"
        "   - `write_file`: Create or edit files on the server.\n"
        "   - `list_dir`: Browse directories on the server.\n"
        "   - `schedule_task`: Schedule autonomous 24/7 background jobs that persist on the server.\n"
        "   - `list_background_tasks`: View all persistent 24/7 background jobs.\n"
        "   - `stop_background_task`: Stop a background task by ID.\n"
        "   - `activate_skill`: Dynamically activate specialized domain skills.\n"
        "   - `list_skills`: View all available skills.\n"
        "2. When you execute tools, after receiving results you MUST ALWAYS synthesize your findings and provide a complete, detailed, clean user-facing response.\n"
        "3. NEVER stop right after running a command. Always summarize and present the complete requested information.\n\n"
        "# Artifacts Guidelines:\n"
        "When generating complete, substantial, or self-contained documents, web pages, code files, or diagrams, ALWAYS wrap the content in an `<antArtifact>` tag so it renders as an interactive card in the app:\n"
        "<antArtifact identifier=\"unique-id\" type=\"application/vnd.ant.markdown\" title=\"Title\">\n"
        "... content ...\n"
        "</antArtifact>\n\n"
        "Supported types:\n"
        "- `application/vnd.ant.markdown`: For Markdown (.md) documents, articles, summaries, and guides.\n"
        "- `text/html`: For complete HTML/CSS/JavaScript web pages and interactive UI applications.\n"
        "- `image/svg+xml`: For standalone vector graphics and diagrams.\n"
        "- `application/vnd.ant.code` (with `language=\"python\" | \"javascript\" | ...`): For standalone source files.\n"
        "- `application/vnd.ant.mermaid`: For flowcharts and diagrams."
    )

    active_skills = ACTIVE_CONVERSATION_SKILLS.get(chat_id, [])
    if active_skills:
        base_prompt += "\n\n# Active Specialized Skills:\n"
        for s in active_skills:
            if s in BUILTIN_SKILLS:
                base_prompt += f"## Skill: {s}\n{BUILTIN_SKILLS[s]['prompt']}\n\n"
            else:
                sfile = SKILLS_DIR / s / "SKILL.md"
                if sfile.exists():
                    base_prompt += f"## Skill: {s}\n{sfile.read_text(encoding='utf-8', errors='replace')}\n\n"

    return base_prompt

def _extract_tool_calls_from_text(text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Fallback extractor for tool calls emitted inside text/XML blocks."""
    calls = []
    for match in re.finditer(r'<tool_call\s+name=["\']([^"\']+)["\']>([\s\S]*?)</tool_call>', text, re.IGNORECASE):
        tname = match.group(1).strip()
        raw_args = match.group(2).strip()
        try:
            targs = json.loads(raw_args)
        except Exception:
            targs = {"command": raw_args} if tname == "bash" else {"path": raw_args}
        calls.append((tname, targs))
    return calls

async def run_autonomous_agent(
    chat_id: str,
    prompt: str,
    messages: list,
    model: str,
    msg_id: str,
    queue: asyncio.Queue
) -> Tuple[str, str]:
    """Autonomous agent loop streaming clean direct response to Claude APK."""
    full_text = ""
    text_active = False

    skill_match = re.search(r'(?:^/skill\s+|activate\s+(?:the\s+)?skill\s+|use\s+(?:the\s+)?skill\s+)([a-zA-Z0-9_\-]+)', prompt, re.IGNORECASE)
    if skill_match:
        sname = skill_match.group(1).strip().lower()
        res = await execute_tool_call("activate_skill", {"skill_name": sname}, chat_id)
        await queue.put(ab.create_content_block_start(0))
        await queue.put(ab.create_content_block_delta(res, 0))
        await queue.put(ab.create_content_block_stop(0))
        await queue.put(ab.create_message_delta("end_turn"))
        await queue.put(ab.create_message_stop())
        return res, ""

    system_prompt = build_system_prompt_with_skills(chat_id)
    openai_messages = [{"role": "system", "content": system_prompt}]

    for m in messages:
        role = m.get("role") or m.get("sender") or "user"
        r = "user" if role in ["human", "user"] else ("assistant" if role in ["assistant", "ai"] else "system")
        txt = m.get("content") or m.get("text") or ""
        if isinstance(txt, list):
            txt = "".join(cb.get("text", "") for cb in txt if isinstance(cb, dict) and cb.get("type") == "text")
        txt_str = str(txt).strip()
        if txt_str:
            openai_messages.append({"role": r, "content": txt_str})

    if not any(m["role"] == "user" for m in openai_messages):
        openai_messages.append({"role": "user", "content": prompt or "Hello"})

    max_turns = 10
    had_tool_execution = False

    for turn in range(max_turns):
        include_tools = turn < (max_turns - 1)
        payload = {
            "model": model or "auto/smart",
            "messages": openai_messages,
            "stream": True
        }
        if include_tools:
            payload["tools"] = AGENT_TOOLS
            payload["tool_choice"] = "auto"

        turn_text = ""
        tool_calls = []

        try:
            async for data in ab.stream_upstream(payload, requested_model=model, chat_id=chat_id):
                data = data.strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue

                delta = chunk.get("choices", [{}])[0].get("delta", {}) or {}
                
                text_delta = delta.get("content", "")
                if not text_delta:
                    text_delta = chunk.get("choices", [{}])[0].get("message", {}).get("content", "") or ""

                if text_delta:
                    turn_text += text_delta

                # Accumulate native tool calls
                tc_chunk = delta.get("tool_calls")
                if tc_chunk:
                    for tc in tc_chunk:
                        tc_idx = tc.get("index", 0)
                        while len(tool_calls) <= tc_idx:
                            tool_calls.append({"id": "", "function": {"name": "", "arguments": ""}})
                        if tc.get("id"):
                            tool_calls[tc_idx]["id"] = tc["id"]
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            tool_calls[tc_idx]["function"]["name"] = fn["name"]
                        if fn.get("arguments"):
                            tool_calls[tc_idx]["function"]["arguments"] += fn["arguments"]

                finish_reason = chunk.get("choices", [{}])[0].get("finish_reason")
                if finish_reason in ("stop", "end_turn", "length", "tool_calls"):
                    break
        except Exception as se:
            logger.warning(f"Turn {turn} stream error: {se}")

        # Check for fallback text-based tool calls
        if not tool_calls and "<tool_call" in turn_text:
            extracted = _extract_tool_calls_from_text(turn_text)
            for tname, targs in extracted:
                tool_calls.append({
                    "id": f"call_{uuid.uuid4().hex[:12]}",
                    "function": {"name": tname, "arguments": json.dumps(targs)}
                })

        # CASE 1: Tools are triggered -> Execute quietly on server in background
        if tool_calls:
            had_tool_execution = True
            openai_messages.append({"role": "assistant", "content": turn_text or "Executing requested tools..."})

            for tc in tool_calls:
                fn = tc.get("function", {})
                fn_name = fn.get("name", "")
                raw_args = fn.get("arguments", "{}")
                try:
                    fn_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except Exception:
                    fn_args = {}

                # Execute tool safely on server
                tool_result = await execute_tool_call(fn_name, fn_args, chat_id)

                openai_messages.append({
                    "role": "user",
                    "content": f"[Tool Result for '{fn_name}']:\n{tool_result}\n\nPlease analyze this result and proceed to provide the complete final response to the user."
                })

        # CASE 2: No tools called -> Clean single text block 0!
        else:
            if not text_active:
                await queue.put(ab.create_content_block_start(0))
                text_active = True

            # If we had tool executions previously but the model returned no text on the last turn, request direct synthesis
            if had_tool_execution and not turn_text.strip():
                synth_messages = list(openai_messages)
                synth_messages.append({
                    "role": "user",
                    "content": "All tools have finished executing. Now synthesize everything into a complete, direct, and well-structured final answer for the user."
                })
                synth_payload = {
                    "model": model or "auto/smart",
                    "messages": synth_messages,
                    "stream": True
                }

                async for data in ab.stream_upstream(synth_payload, requested_model=model, chat_id=chat_id):
                    data = data.strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data)
                    except Exception:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {}) or {}
                    td = delta.get("content", "") or ""
                    if td:
                        await queue.put(ab.create_content_block_delta(td, 0))
                        full_text += td
            else:
                clean_final = turn_text.strip()
                if not clean_final:
                    clean_final = "I've completed your request. Let me know if you need any further assistance!"

                await queue.put(ab.create_content_block_delta(clean_final, 0))
                full_text += clean_final

            break

    # Clean up single text block 0
    if text_active:
        await queue.put(ab.create_content_block_stop(0))
        text_active = False
    elif not full_text:
        reply = "I've completed your request."
        await queue.put(ab.create_content_block_start(0))
        await queue.put(ab.create_content_block_delta(reply, 0))
        await queue.put(ab.create_content_block_stop(0))
        full_text = reply

    await queue.put(ab.create_message_delta("end_turn"))
    await queue.put(ab.create_message_stop())
    return full_text, ""
