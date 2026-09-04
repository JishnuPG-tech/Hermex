import asyncio
import os
import signal
from hermes_core.tools.registry import registry

@registry.register(
    name="bash_exec",
    description=(
        "Execute a bash command or shell script directly on the Hermes Agent server "
        "container. Use this for real server operations: inspect/read files, write or "
        "edit files, run tests and services, install apt/pip/npm packages, clone/pull/"
        "commit/push git repositories, and inspect processes or logs. The command has "
        "the server's normal filesystem, network, environment, and installed tools; "
        "do not claim an action succeeded until the command output confirms it."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The bash command or script to execute on the Hermes server"},
            "working_directory": {
                "type": "string",
                "description": "Directory in which to run the command. Defaults to HERMES_SERVER_WORKDIR or /app.",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Maximum runtime in seconds (1-600). Defaults to 120; use a larger value for package installs or builds.",
                "minimum": 1,
                "maximum": 600,
            },
            "max_output_chars": {
                "type": "integer",
                "description": "Maximum combined stdout/stderr characters returned to the agent (1,000-50,000). Defaults to 12,000.",
                "minimum": 1000,
                "maximum": 50000,
            },
        },
        "required": ["command"],
    },
    category="coding",
)
async def bash_exec(
    command: str,
    working_directory: str | None = None,
    timeout_seconds: int = 120,
    max_output_chars: int = 12000,
) -> str:
    timeout_seconds = max(1, min(int(timeout_seconds), 600))
    max_output_chars = max(1000, min(int(max_output_chars), 50000))
    cwd = working_directory or os.getenv("HERMES_SERVER_WORKDIR", "/app")
    proc = None
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            executable="/bin/bash",
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=float(timeout_seconds),
            )
            out_str = stdout.decode("utf-8", errors="replace").strip()
            err_str = stderr.decode("utf-8", errors="replace").strip()
            res = ""
            if out_str:
                res += f"[STDOUT]\n{out_str}\n"
            if err_str:
                res += f"[STDERR]\n{err_str}\n"
            res += f"[EXIT CODE: {proc.returncode}]"
            if len(res) > max_output_chars:
                res = (
                    res[:max_output_chars]
                    + f"\n[OUTPUT TRUNCATED at {max_output_chars} characters]"
                )
            return res
        except asyncio.TimeoutError:
            os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
            return f"[ERROR] Command execution timed out after {timeout_seconds} seconds."
        except asyncio.CancelledError:
            os.killpg(proc.pid, signal.SIGKILL)
            await proc.wait()
            raise
    except Exception as e:
        return f"[ERROR] Server command execution failed in {cwd}: {str(e)}"

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
