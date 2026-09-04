import asyncio
import subprocess
from hermes_core.tools.registry import registry

@registry.register(
    name="bash_exec",
    description="Execute a bash command or shell script in a safe sandboxed environment.",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to execute"}
        },
        "required": ["command"]
    },
    category="coding"
)
async def bash_exec(command: str) -> str:
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            out_str = stdout.decode("utf-8", errors="replace").strip()
            err_str = stderr.decode("utf-8", errors="replace").strip()
            res = ""
            if out_str:
                res += f"[STDOUT]\n{out_str}\n"
            if err_str:
                res += f"[STDERR]\n{err_str}\n"
            res += f"[EXIT CODE: {proc.returncode}]"
            return res[:5000]
        except asyncio.TimeoutError:
            proc.kill()
            return "[ERROR] Command execution timed out after 15 seconds."
    except Exception as e:
        return f"[ERROR] Execution failed: {str(e)}"

@registry.register(
    name="python_exec",
    description="Execute Python code and return the output or calculated result.",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "The Python code snippet to execute"}
        },
        "required": ["code"]
    },
    category="coding"
)
async def python_exec(code: str) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", "-c", code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        out_str = stdout.decode("utf-8", errors="replace").strip()
        err_str = stderr.decode("utf-8", errors="replace").strip()
        if err_str:
            return f"{out_str}\n[ERR: {err_str}]"
        return out_str or "[Executed successfully with no stdout]"
    except Exception as e:
        return f"[Python Error]: {str(e)}"
