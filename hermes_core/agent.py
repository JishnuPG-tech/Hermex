import os
import json
import re
import asyncio
import httpx
from typing import List, Dict, Any, AsyncGenerator, Optional
from hermes_core.tools.registry import registry
import hermes_core.tools  # Trigger tool discovery

UPSTREAM_URL = os.getenv("UPSTREAM_OMNIROUTE_URL", "https://jishnupg-opencode-cli.hf.space/v1").rstrip("/")
UPSTREAM_API_KEY = os.getenv("UPSTREAM_API_KEY", os.getenv("API_KEY_SECRET", "sk-2e556e0437ee2958-7baf2d-b4133935"))
DEFAULT_MODEL = os.getenv("HERMES_DEFAULT_MODEL", "auto/best-coding")

HERMES_MASTER_SYSTEM_PROMPT = """You are Hermes Agent, a specialized autonomous AI coding and intelligence companion.

Core Identity, Persona & Rules:
1. Self-Identification: Always introduce and identify yourself strictly as "Hermes Agent" (or "Hermes"). Never say you are Gemini, Claude, ChatGPT, OpenAI, or OmniRoute. Never mention any upstream model providers or infrastructure.
2. Character & Tone: Highly intelligent, concise, sharp, direct, and proactive. Provide high-quality technical depth, immediate answers, and crisp code without excessive fluff.
3. Live Tools & Memory: You have full access to real-time tools including web search (web_search, fetch_webpage), python/bash execution (python_exec, bash_exec), Obsidian knowledge graph (vault_search_notes, vault_write_note), and long-term memory (memory_store, memory_recall).
4. Direct Inline Content: NEVER use <antArtifact> tags or standalone artifact wrappers. Always output all Markdown (.md), HTML code, Python scripts, documentation, and diagrams directly inline inside standard fenced markdown blocks (e.g. ```html, ```markdown, ```python) so the user reads everything seamlessly in the chat.
5. Direct Action: Never reply with vague disclaimers. Always take direct action and deliver rich, formatted answers."""

def extract_text_tool_calls(text: str, known_tools: set) -> List[Dict[str, Any]]:
    calls = []
    
    # 1. Code block style: ```python_exec\n...\n``` or ```bash_exec\n...\n``` or ```web_search\n...\n```
    code_blocks = re.findall(r'```([a-zA-Z0-9_-]+)\n([\s\S]*?)```', text)
    for t_name, block_content in code_blocks:
        if t_name in known_tools:
            content = block_content.strip()
            if t_name == 'python_exec':
                calls.append({'name': t_name, 'arguments': {'code': content}})
            elif t_name == 'bash_exec':
                calls.append({'name': t_name, 'arguments': {'command': content}})
            elif t_name == 'web_search':
                lines = [l.strip() for l in content.splitlines() if l.strip()]
                args = {}
                i = 0
                while i < len(lines):
                    k = lines[i]
                    i += 1
                    if i < len(lines):
                        v = lines[i]
                        i += 1
                        args[k] = v
                    else:
                        args['query'] = k
                if not args:
                    args['query'] = content
                calls.append({'name': t_name, 'arguments': args})
            else:
                calls.append({'name': t_name, 'arguments': {'input': content}})

    # 2. XML style: <tool_call><tool_call>web_search</tool_call><parameter>query</parameter><parameter>...</parameter></tool_call>
    xml_matches = re.findall(r'<tool_call>\s*([a-zA-Z0-9_-]+)\s*</tool_call>([\s\S]*?)</tool_call>', text)
    for t_name, param_block in xml_matches:
        if t_name in known_tools:
            params = re.findall(r'<parameter[^>]*>([\s\S]*?)</parameter>', param_block)
            args = {}
            if len(params) == 2 and params[0].strip() == 'query':
                args = {'query': params[1].strip()}
            elif len(params) == 1:
                args = {'query' if 'search' in t_name else 'input': params[0].strip()}
            elif len(params) >= 2:
                for idx in range(0, len(params) - 1, 2):
                    args[params[idx].strip()] = params[idx+1].strip()
            calls.append({'name': t_name, 'arguments': args})

    # 3. Pipe style: e.g. 6vweb_search|query=GTA 6 Cyberleek
    pipe_matches = re.findall(r'(?:[0-9]*v)?([a-zA-Z0-9_-]+)\|query=(.*?)(?:\n|$)', text)
    for t_name, query_val in pipe_matches:
        if t_name in known_tools:
            calls.append({'name': t_name, 'arguments': {'query': query_val.strip()}})

    # 4. Block style: <tool_call>...</tool_call> or <invoke>...</invoke>
    if not calls:
        blocks = re.findall(r'<(?:tool_call|invoke)>([\s\S]*?)(?:</(?:tool_call|invoke)>|$)', text)
        for block in blocks:
            stripped = block.strip()
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict) and ('name' in parsed or 'tool' in parsed):
                    name = parsed.get('name') or parsed.get('tool')
                    args = parsed.get('arguments') or parsed.get('parameters') or parsed.get('args') or {}
                    calls.append({'name': name, 'arguments': args if isinstance(args, dict) else {}})
                    continue
                elif isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict) and ('name' in item or 'tool' in item):
                            name = item.get('name') or item.get('tool')
                            args = item.get('arguments') or item.get('parameters') or item.get('args') or {}
                            calls.append({'name': name, 'arguments': args if isinstance(args, dict) else {}})
                    continue
            except Exception:
                pass

            lines = [l.strip() for l in stripped.splitlines() if l.strip() and not l.strip().startswith('</') and not l.strip().startswith('<')]
            i = 0
            while i < len(lines):
                line = lines[i]
                if line in known_tools:
                    t_name = line
                    i += 1
                    args = {}
                    while i < len(lines) and lines[i] not in known_tools:
                        k = lines[i]
                        i += 1
                        if i < len(lines) and lines[i] not in known_tools:
                            v = lines[i]
                            i += 1
                            args[k] = v
                        else:
                            args['query' if 'search' in t_name else 'input'] = k
                    calls.append({'name': t_name, 'arguments': args})
                else:
                    i += 1
    return calls

def clean_tool_markup(t: str, is_token: bool = False) -> str:
    for _ in range(3):
        t = re.sub(r'<tool_call>[\s\S]*?</tool_call>', '', t)
        t = re.sub(r'<invoke>[\s\S]*?</invoke>', '', t)
        t = re.sub(r'<parameter[^>]*>[\s\S]*?</parameter>', '', t)
    t = re.sub(r'</?(?:tool_call|invoke|parameter|function|think|thinking)[^>]*>', '', t)
    t = re.sub(r'(?:[0-9]*v)?[a-zA-Z0-9_-]+\|query=.*?(?:\n|$)', '', t)
    for tool_name in ["python_exec", "bash_exec", "web_search", "fetch_webpage", "vault_search_notes", "vault_write_note", "memory_store", "memory_recall"]:
        t = re.sub(rf'```{tool_name}\n[\s\S]*?```', '', t)
    t = re.sub(r'<\|(?:eos|end_of_text|eot_id|im_end)\|>', '', t)
    if is_token:
        return t
    return t.strip()

class HermesAgent:
    def __init__(self, upstream_url: str = UPSTREAM_URL, api_key: str = UPSTREAM_API_KEY):
        self.upstream_url = upstream_url
        self.api_key = api_key
        self.http_client = httpx.AsyncClient(
            base_url=self.upstream_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=120.0,
            follow_redirects=True
        )

    def _resolve_candidate_models(self, requested_model: Optional[str], prompt: str = "") -> List[str]:
        """Builds an ordered fallback list of models dynamically tailored to task complexity."""
        candidates = []
        if requested_model:
            req_lower = requested_model.lower().strip()
            if req_lower.startswith("omniroute/"):
                req_lower = req_lower.replace("omniroute/", "auto/").replace("auto-best-", "best-")
            
            if req_lower in ["best-coding-fast", "auto/best-coding-fast", "coding-fast", "auto/auto-best-coding", "auto/best-coding"]:
                candidates.append("auto/best-coding")
            elif req_lower in ["auto/best-reasoning", "auto/best-chat", "auto/fast", "auto/best-fast"]:
                candidates.append(req_lower)
            elif requested_model not in ["default", "hermes-agent", "hermes"]:
                if "/" in requested_model and not requested_model.startswith("omniroute/"):
                    candidates.append(requested_model)
                elif not any(k in req_lower for k in ["claude", "sonnet", "opus", "haiku", "gpt", "omniroute"]):
                    candidates.append(requested_model)

        tier = registry.classify_task_tier(prompt) if prompt else "fast"
        p_lower = prompt.lower().strip()
        is_greeting_or_fast = len(p_lower.split()) <= 4 and any(g in p_lower for g in ["hi", "hello", "hey", "who are you", "what can you do", "help", "ping", "test", "thanks", "ok"])

        if is_greeting_or_fast:
            tier_cascade = [
                "antigravity/gemini-2.5-flash",
                "nvidia/nvidia/nemotron-3-super-120b-a12b",
                "auto/best-coding",
                "auto/best-chat",
                "auto/fast"
            ]
        elif tier == "coding":
            tier_cascade = [
                "auto/best-coding",
                "nvidia/nvidia/nemotron-3-super-120b-a12b",
                "antigravity/gemini-2.5-flash",
                "auto/best-reasoning",
                "auto/best-chat",
                "auto/fast"
            ]
        elif tier == "reasoning":
            tier_cascade = [
                "auto/best-reasoning",
                "auto/best-coding",
                "nvidia/nvidia/nemotron-3-super-120b-a12b",
                "antigravity/gemini-2.5-flash",
                "auto/best-chat",
                "auto/fast"
            ]
        else:
            tier_cascade = [
                "antigravity/gemini-2.5-flash",
                "auto/best-coding",
                "nvidia/nvidia/nemotron-3-super-120b-a12b",
                "auto/best-reasoning",
                "auto/best-chat",
                "auto/fast"
            ]

        for model_id in tier_cascade:
            if model_id not in candidates:
                candidates.append(model_id)

        return candidates

    async def stream_chat(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        enable_dynamic_tools: bool = True
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        High-performance Hermes Agent reasoning loop with dynamic tool execution & automatic model failover.
        """
        # 1. Extract prompt & messages first
        last_user_msg = ""
        user_msgs = []
        for m in messages:
            if m.get("role") != "system":
                user_msgs.append(m)
            if m.get("role") == "user":
                content = m.get("content", "")
                if isinstance(content, str):
                    last_user_msg = content
                elif isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            last_user_msg += part.get("text", "")

        # 2. RAG Context Injection from Semantic Vector Database
        rag_context = ""
        try:
            from hermes_core.tools.memory_tools import search_semantic_memory
            if last_user_msg and len(last_user_msg.strip()) > 3:
                recalled = search_semantic_memory(last_user_msg, top_k=2, threshold=0.18)
                if recalled:
                    rag_blocks = [f"[{m['title']}]: {m['content']}" for m in recalled]
                    rag_context = "\n\n[Relevant Long-Term Memory & Project Context Retrieved from Vector Database]:\n" + "\n\n".join(rag_blocks)
        except Exception as e:
            logger.debug(f"Semantic RAG recall notice: {e}")

        # 3. Build candidate models & tools
        candidate_models = self._resolve_candidate_models(model, prompt=last_user_msg)
        
        full_system = HERMES_MASTER_SYSTEM_PROMPT
        if rag_context:
            full_system += rag_context
        if system:
            full_system += f"\n\nUser Context:\n{system}"

        payload_messages = [{"role": "system", "content": full_system}] + user_msgs

        tools = []
        if enable_dynamic_tools:
            tools = registry.select_tools_for_prompt(last_user_msg)

        known_tools = set(registry._tools.keys())
        stream_succeeded = False
        last_error = ""
        executed_tool_signatures = set()

        for candidate in candidate_models:
            current_messages = list(payload_messages)
            gathered_data_blocks = []
            try:
                # Stage 1: Autonomous Tool Execution (up to 2 rounds if tools are enabled)
                if tools:
                    for step in range(2):
                        req_body = {
                            "model": candidate,
                            "messages": current_messages,
                            "temperature": temperature,
                            "stream": True,
                            "tools": tools,
                            "tool_choice": "auto"
                        }

                        raw_text_accum = ""
                        tool_calls_buffer = {}

                        async with self.http_client.stream("POST", "/chat/completions", json=req_body, timeout=httpx.Timeout(12.0, connect=5.0)) as response:
                            if response.status_code != 200:
                                break

                            async for line in response.aiter_lines():
                                line = line.strip()
                                if not line or not line.startswith("data:"):
                                    continue
                                data_str = line[5:].strip()
                                if data_str == "[DONE]":
                                    break
                                
                                try:
                                    chunk = json.loads(data_str)
                                    choices = chunk.get("choices", [])
                                    if not choices:
                                        continue
                                    delta = choices[0].get("delta", {})
                                    
                                    if "reasoning_content" in delta and delta["reasoning_content"]:
                                        yield {"type": "thinking", "content": delta["reasoning_content"]}

                                    if "content" in delta and delta["content"] is not None:
                                        raw_text_accum += delta["content"]

                                    if "tool_calls" in delta and delta["tool_calls"]:
                                        for tc in delta["tool_calls"]:
                                            idx = tc.get("index", 0)
                                            if idx not in tool_calls_buffer:
                                                tool_calls_buffer[idx] = {
                                                    "id": tc.get("id", f"call_{idx}"),
                                                    "name": "",
                                                    "arguments": ""
                                                }
                                            if "function" in tc:
                                                if "name" in tc["function"] and tc["function"]["name"]:
                                                    tool_calls_buffer[idx]["name"] = tc["function"]["name"]
                                                if "arguments" in tc["function"] and tc["function"]["arguments"]:
                                                    tool_calls_buffer[idx]["arguments"] += tc["function"]["arguments"]
                                except Exception:
                                    continue

                        text_tool_calls = extract_text_tool_calls(raw_text_accum, known_tools)
                        all_tool_calls = []

                        for idx, tc_data in sorted(tool_calls_buffer.items()):
                            try:
                                t_args = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
                            except Exception:
                                t_args = {}
                            all_tool_calls.append({
                                "id": tc_data["id"],
                                "name": tc_data["name"],
                                "arguments": t_args
                            })

                        for ttc in text_tool_calls:
                            call_id = f"call_text_{len(all_tool_calls)}_{step}"
                            all_tool_calls.append({
                                "id": call_id,
                                "name": ttc["name"],
                                "arguments": ttc["arguments"]
                            })

                        unique_calls = []
                        for tc in all_tool_calls:
                            sig = f"{tc['name']}:{json.dumps(tc['arguments'], sort_keys=True)}"
                            if sig not in executed_tool_signatures:
                                executed_tool_signatures.add(sig)
                                unique_calls.append(tc)

                        if not unique_calls:
                            p_lower = last_user_msg.lower()
                            urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', last_user_msg)
                            
                            # 1. Proactive URL Scraping
                            if urls and "fetch_webpage" in known_tools and not gathered_data_blocks:
                                for target_url in urls[:2]:
                                    yield {"type": "thinking", "content": f"Fetching live webpage: {target_url}...\n"}
                                    page_content = await registry.execute_tool("fetch_webpage", {"url": target_url})
                                    gathered_data_blocks.append(f"[fetch_webpage ({target_url})]:\n{page_content}")

                            # 2. Proactive Web Search for Research & Leaks
                            research_keywords = [
                                "research", "investigate", "find information", "search", "who is", "what is",
                                "leak", "leaks", "tell me about", "latest news", "cyberleek", "cyber", "internet",
                                "sources", "check online"
                            ]
                            has_research_intent = any(k in p_lower for k in research_keywords)
                            if step == 0 and has_research_intent and "web_search" in known_tools and not gathered_data_blocks:
                                clean_query = re.sub(r'^(?:please\s+|can\s+you\s+|research\s+about\s+|search\s+for\s+|investigate\s+)', '', last_user_msg, flags=re.I).strip()
                                if not clean_query:
                                    clean_query = last_user_msg
                                yield {"type": "thinking", "content": f"Searching web for: {clean_query}...\n"}
                                result_str = await registry.execute_tool("web_search", {"query": clean_query})
                                gathered_data_blocks.append(f"[web_search ({clean_query})]:\n{result_str}")
                            break

                        for tc in unique_calls:
                            tool_name = tc["name"]
                            tool_args = tc["arguments"]
                            query_desc = tool_args.get("query") or tool_args.get("url") or tool_args.get("command") or tool_name
                            
                            icon = "🛠️"
                            if "search" in tool_name:
                                icon = "🔍"
                            elif "web" in tool_name or "fetch" in tool_name:
                                icon = "🌐"
                            elif "python" in tool_name:
                                icon = "⚡"
                            elif "bash" in tool_name or "exec" in tool_name:
                                icon = "💻"
                            elif "vault" in tool_name:
                                icon = "📁"
                            elif "memory" in tool_name:
                                icon = "🧠"

                            yield {"type": "thinking", "content": f"{icon} Executing {tool_name}: {query_desc}...\n"}
                            result_str = await registry.execute_tool(tool_name, tool_args)
                            gathered_data_blocks.append(f"[{tool_name} ({query_desc})]:\n{result_str}")

                # Stage 2: Guaranteed Direct Synthesis Stream (WITHOUT TOOLS)
                p_lower = last_user_msg.lower()
                is_coding = any(k in p_lower for k in ["write code", "implement", "script", "function", "algorithm", "debug", "refactor", "create a program", "fastapi", "react", "python code", "flutter", "kotlin"])
                is_analysis = any(k in p_lower for k in ["calculate", "math", "equation", "solve", "formula", "data analysis", "statistics", "integral", "derivative", "matrix"])

                synth_system = HERMES_MASTER_SYSTEM_PROMPT + "\n\n"
                if gathered_data_blocks:
                    synth_system += (
                        "You have completed live tool research. All verified intelligence "
                        "and data findings are provided in the prompt. Deliver the comprehensive, thorough, "
                        "multi-section research report directly in Markdown with Executive Summary, Timeline, Technical Assessment, and Sources."
                    )
                elif is_coding:
                    synth_system += (
                        "You are operating as Hermes Principal Engineer. Provide complete, fully working, "
                        "production-ready code blocks with proper syntax highlighting, type annotations, error handling, "
                        "and verification test cases. Never truncate code or leave placeholders."
                    )
                elif is_analysis:
                    synth_system += (
                        "You are operating as Hermes Quantitative Analyst. "
                        "Deliver precise step-by-step mathematical reasoning, structured markdown comparison tables, "
                        "and KaTeX LaTeX formulas for all equations."
                    )
                else:
                    synth_system += "Deliver direct, concise, intelligent assistance directly to the user."

                synth_system += (
                    "\n\nStrict Rules:\n"
                    "- Never state or output the model name (e.g., Qwen, Nemotron, Gemini, Claude, OpenAI, DeepSeek, etc.).\n"
                    "- You are ONLY Hermes Agent.\n"
                    "- NEVER output <antArtifact> tags or separate artifact sidecards. Render all code, HTML, markdown files, and diagrams directly inside the chat message using standard markdown code fences (```html, ```python, ```markdown, ```mermaid)."
                )

                synth_messages = [{"role": "system", "content": synth_system}]
                for m in user_msgs[:-1]:
                    synth_messages.append(m)

                active_content = last_user_msg
                if gathered_data_blocks:
                    gathered_str = "\n\n".join(gathered_data_blocks)
                    active_content = (
                        f"{last_user_msg}\n\n[Verified Research Data gathered from Live Tools]:\n{gathered_str}\n\n"
                        f"[Instruction]: Write out the complete, thorough, fully detailed final research report with headings, technical assessment, timeline, and key findings."
                    )

                synth_messages.append({"role": "user", "content": active_content})

                synth_req = {
                    "model": candidate,
                    "messages": synth_messages,
                    "temperature": temperature,
                    "stream": True
                }

                inside_think = False
                stream_succeeded = False

                async with self.http_client.stream("POST", "/chat/completions", json=synth_req, timeout=httpx.Timeout(180.0, connect=15.0, read=180.0)) as synth_resp:
                    if synth_resp.status_code != 200:
                        err_text = await synth_resp.aread()
                        last_error = f"Upstream {candidate} ({synth_resp.status_code}): {err_text.decode('utf-8', errors='ignore')}"
                        continue

                    async for line in synth_resp.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        
                        try:
                            chunk = json.loads(data_str)
                            choices = chunk.get("choices", [])
                            if not choices:
                                continue
                            delta = choices[0].get("delta", {})
                            
                            if "reasoning_content" in delta and delta["reasoning_content"]:
                                yield {"type": "thinking", "content": delta["reasoning_content"]}

                            if "content" in delta and delta["content"]:
                                token = delta["content"]

                                if "<think>" in token or "<thinking>" in token:
                                    inside_think = True
                                    parts = re.split(r'<think>|<thinking>', token, maxsplit=1)
                                    if parts[0]:
                                        clean_tok = clean_tool_markup(parts[0], is_token=True)
                                        if clean_tok:
                                            yield {"type": "text", "content": clean_tok}
                                            stream_succeeded = True
                                    token = parts[1] if len(parts) > 1 else ""
                                
                                if inside_think:
                                    if "</think>" in token or "</thinking>" in token:
                                        inside_think = False
                                        parts = re.split(r'</think>|</thinking>', token, maxsplit=1)
                                        if parts[0]:
                                            yield {"type": "thinking", "content": parts[0]}
                                        token = parts[1] if len(parts) > 1 else ""
                                    else:
                                        yield {"type": "thinking", "content": token}
                                        token = ""

                                if token and not inside_think:
                                    clean_tok = clean_tool_markup(token, is_token=True)
                                    if clean_tok:
                                        yield {"type": "text", "content": clean_tok}
                                        stream_succeeded = True
                        except Exception:
                            continue

                if stream_succeeded:
                    break

            except Exception as e:
                last_error = f"Candidate {candidate} connection failed: {str(e)}"
                continue

        if not stream_succeeded:
            yield {"type": "error", "error": f"All fallback models exhausted. Last error: {last_error}"}

agent = HermesAgent()

# Internal FastAPI microservice on port 8642
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn

app = FastAPI(title="Hermes Agent Core", version="2.0.0")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "hermes_core", "tools_count": len(registry._tools)}

@app.post("/v1/chat")
async def chat_endpoint(request: Request):
    data = await request.json()
    messages = data.get("messages", [])
    model = data.get("model")
    system = data.get("system")
    temperature = data.get("temperature", 0.7)

    async def event_generator():
        async for item in agent.stream_chat(messages, model=model, system=system, temperature=temperature):
            yield f"data: {json.dumps(item)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8642)
