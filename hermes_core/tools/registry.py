import json
import inspect
import re
from typing import Dict, Any, List, Callable, Optional

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._handlers: Dict[str, Callable] = {}
        self._categories: Dict[str, List[str]] = {
            "web": [],
            "coding": [],
            "vault": [],
            "memory": [],
            "system": []
        }
        self._enabled_categories: set = {"web", "coding", "vault", "memory", "system"}

    def register(self, name: str, description: str, parameters: Dict[str, Any], category: str = "system"):
        def decorator(fn: Callable):
            schema = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters
                }
            }
            self._tools[name] = {
                "schema": schema,
                "category": category,
                "description": description
            }
            self._handlers[name] = fn
            if category not in self._categories:
                self._categories[category] = []
            if name not in self._categories[category]:
                self._categories[category].append(name)
            return fn
        return decorator

    def enable_category(self, category: str):
        self._enabled_categories.add(category)

    def disable_category(self, category: str):
        self._enabled_categories.discard(category)

    def get_all_tools(self) -> List[Dict[str, Any]]:
        return [
            meta["schema"] for name, meta in self._tools.items()
            if meta["category"] in self._enabled_categories
        ]

    def select_tools_for_prompt(self, prompt: str, user_requested_tools: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Dynamic context-aware tool selection.
        Analyzes prompt intent to only load schemas relevant to the query,
        saving prompt tokens and avoiding hallucinations.
        """
        if user_requested_tools:
            return [
                self._tools[name]["schema"] for name in user_requested_tools
                if name in self._tools and self._tools[name]["category"] in self._enabled_categories
            ]

        p = prompt.lower()
        selected_categories = set()

        # Web search intent
        if any(w in p for w in ["search", "google", "web", "latest", "news", "find online", "who is", "what is the current", "url", "http", "research", "investigate", "look up", "leak", "leaks", "find out", "check online", "sources", "information on", "about", "cyber", "internet"]):
            selected_categories.add("web")

        # Coding / execution intent
        if any(w in p for w in ["code", "python", "bash", "execute", "run", "script", "terminal", "calculate", "math", "program", "debug"]):
            selected_categories.add("coding")

        # Obsidian vault / notes intent
        if any(w in p for w in ["note", "vault", "obsidian", "save note", "read note", "journal", "document", "knowledge"]):
            selected_categories.add("vault")

        # Memory / recall intent
        if any(w in p for w in ["remember", "memory", "recall", "who am i", "my name", "preferences", "past conversation"]):
            selected_categories.add("memory")

        # If it is general conversational chat without active tool needs, return empty list (0ms tool overhead)
        if not selected_categories:
            # If prompt mentions specific keywords or starts with question words, enable web + memory fallback
            if any(w in p for w in ["how to", "why", "where", "tell me about"]):
                selected_categories.add("web")
                selected_categories.add("memory")
            else:
                return []

        # Collect schemas
        result = []
        for cat in selected_categories:
            if cat in self._enabled_categories:
                for tool_name in self._categories.get(cat, []):
                    result.append(self._tools[tool_name]["schema"])
        return result

    async def execute_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        if name not in self._handlers:
            return json.dumps({"error": f"Tool '{name}' not found."})
        fn = self._handlers[name]
        try:
            if inspect.iscoroutinefunction(fn):
                res = await fn(**arguments)
            else:
                res = fn(**arguments)
            if isinstance(res, (dict, list)):
                return json.dumps(res, ensure_ascii=False)
            return str(res)
        except Exception as e:
            return json.dumps({"error": f"Tool execution failed: {str(e)}"})


    def classify_task_tier(self, prompt: str) -> str:
        """
        Intelligently determines the ideal model tier based on query complexity.
        - 'coding': Complex software engineering, programming, scripting, debugging -> auto/best-coding
        - 'reasoning': Deep analysis, logic puzzles, multi-step research, architecture -> auto/best-reasoning
        - 'chat': High-quality conversational, creative writing -> auto/best-chat
        - 'fast': Quick questions, greetings, everyday conversation -> auto/best-fast
        """
        p = prompt.lower()
        
        # Coding & Debugging
        if any(w in p for w in ["def ", "class ", "function", "import ", "sql", "html", "css", "javascript", "python", "dockerfile", "refactor", "bug", "traceback", "syntaxerror", "write a script", "code"]):
            return "coding"
            
        # Deep Reasoning & Research
        if any(w in p for w in ["research", "investigate", "compare and contrast", "architect", "deep dive", "prove", "step-by-step reasoning", "analyze tradeoffs", "strategy", "algorithm", "full report", "detailed report"]):
            return "reasoning"

        # General High Quality
        if len(prompt.split()) > 40:
            return "chat"
            
        # Fast Everyday Interaction
        return "fast"

registry = ToolRegistry()
