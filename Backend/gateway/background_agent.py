import os
import re
import json
import uuid
import time
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("hermes.background_agent")
logging.basicConfig(level=logging.INFO)

TASKS_DIR = Path("/data/hermes") if Path("/data/hermes").exists() else Path("/tmp/hermes")
TASKS_DIR.mkdir(parents=True, exist_ok=True)
TASKS_FILE = TASKS_DIR / "scheduled_tasks.json"
TASK_LOGS_DIR = TASKS_DIR / "task_logs"
TASK_LOGS_DIR.mkdir(parents=True, exist_ok=True)

# In-memory registry of active background jobs
_TASKS: Dict[str, Dict[str, Any]] = {}
_RUNNING_HANDLES: Dict[str, asyncio.Task] = {}

def _load_tasks():
    global _TASKS
    if TASKS_FILE.exists():
        try:
            _TASKS = json.loads(TASKS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"Error loading tasks: {e}")
            _TASKS = {}

def _save_tasks():
    try:
        TASKS_FILE.write_text(json.dumps(_TASKS, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.error(f"Error saving tasks: {e}")

_load_tasks()

def append_task_log(task_id: str, message: str):
    try:
        log_file = TASK_LOGS_DIR / f"{task_id}.log"
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")
    except Exception:
        pass

async def execute_task_iteration(task_id: str):
    """Executes a single iteration of a 24/7 background agent job."""
    task = _TASKS.get(task_id)
    if not task or not task.get("enabled", True):
        return

    name = task.get("name", task_id)
    instruction = task.get("instruction", "")
    task_type = task.get("type", "agent") # "agent" or "bash"
    chat_id = task.get("chat_id", "background_autonomous_session")
    
    append_task_log(task_id, f"=== Starting execution of task '{name}' ===")
    task["last_run_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    task["run_count"] = task.get("run_count", 0) + 1
    task["status"] = "RUNNING"
    _save_tasks()

    result_summary = ""
    try:
        if task_type == "bash":
            # Direct bash command execution
            proc = await asyncio.create_subprocess_shell(
                instruction,
                cwd=str(TASKS_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
            out_str = stdout.decode("utf-8", errors="replace")
            err_str = stderr.decode("utf-8", errors="replace")
            result_summary = f"Exit code: {proc.returncode}\n{out_str}\n{err_str}".strip()
            append_task_log(task_id, result_summary)

        else:
            # Autonomous LLM Agent Execution with tools (bash, read_file, write_file, skills)
            from gateway import agent_executor as ae
            from gateway import claude_rest_api as cra
            
            queue = asyncio.Queue()
            messages = [{"role": "user", "content": f"[24x7 Scheduled Autonomous Task]: {instruction}"}]
            
            result_summary = await ae.run_autonomous_agent(
                chat_id=chat_id,
                prompt=instruction,
                messages=messages,
                model=task.get("model", "auto/smart"),
                msg_id=f"bg_msg_{uuid.uuid4().hex[:16]}",
                queue=queue
            )
            append_task_log(task_id, f"Agent result: {result_summary}")

            # Notify channels if enabled (e.g. Telegram / Email / Webhook)
            if task.get("notify_channels", False):
                try:
                    from gateway import channels_manager as cm
                    await cm.broadcast_message(f"🔔 **[24/7 Agent Task: {name}]**\n\n{result_summary}")
                except Exception as ne:
                    append_task_log(task_id, f"Notification error: {ne}")

        task["last_result"] = result_summary[:1000]
        task["status"] = "SUCCESS"
    except Exception as e:
        logger.error(f"Task '{name}' failed: {e}")
        append_task_log(task_id, f"ERROR: {str(e)}")
        task["status"] = "FAILED"
        task["last_result"] = f"Error: {str(e)}"
    finally:
        _save_tasks()
        append_task_log(task_id, f"=== Finished execution of task '{name}' ===")

async def _task_loop(task_id: str):
    """Background worker loop that triggers recurring intervals or continuous daemon loops."""
    while True:
        task = _TASKS.get(task_id)
        if not task:
            break
        if not task.get("enabled", True):
            await asyncio.sleep(10)
            continue

        interval = int(task.get("interval_seconds", 300))
        if interval < 10:
            interval = 10 # Safety lower bound

        try:
            await execute_task_iteration(task_id)
        except Exception as e:
            logger.error(f"Unhandled error in task loop {task_id}: {e}")

        # Sleep until next scheduled iteration
        await asyncio.sleep(interval)

def schedule_job(
    name: str,
    instruction: str,
    interval_seconds: int = 300,
    task_type: str = "agent",
    notify_channels: bool = False,
    chat_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create and register a 24/7 persistent background task."""
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    task_data = {
        "id": task_id,
        "name": name,
        "instruction": instruction,
        "type": task_type,
        "interval_seconds": max(15, interval_seconds),
        "notify_channels": notify_channels,
        "chat_id": chat_id or "background_autonomous_session",
        "enabled": True,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "last_run_at": None,
        "run_count": 0,
        "status": "SCHEDULED",
        "last_result": None
    }
    _TASKS[task_id] = task_data
    _save_tasks()

    # Start loop in background
    handle = asyncio.create_task(_task_loop(task_id))
    _RUNNING_HANDLES[task_id] = handle
    append_task_log(task_id, f"Task '{name}' registered with {interval_seconds}s interval.")
    return task_data

def cancel_job(task_id: str) -> bool:
    """Stop and remove a 24/7 background task."""
    if task_id in _RUNNING_HANDLES:
        _RUNNING_HANDLES[task_id].cancel()
        del _RUNNING_HANDLES[task_id]
    if task_id in _TASKS:
        _TASKS[task_id]["enabled"] = False
        _TASKS[task_id]["status"] = "STOPPED"
        _save_tasks()
        return True
    return False

def get_all_jobs() -> List[Dict[str, Any]]:
    """Return all scheduled tasks."""
    return list(_TASKS.values())

def get_job_logs(task_id: str) -> str:
    """Retrieve logs for a task."""
    log_file = TASK_LOGS_DIR / f"{task_id}.log"
    if log_file.exists():
        return log_file.read_text(encoding="utf-8", errors="replace")
    return "(No logs recorded yet)"

def start_all_saved_jobs():
    """Restores and starts all persistent background tasks upon container boot."""
    _load_tasks()
    started = 0
    for task_id, task in _TASKS.items():
        if task.get("enabled", True) and task_id not in _RUNNING_HANDLES:
            handle = asyncio.create_task(_task_loop(task_id))
            _RUNNING_HANDLES[task_id] = handle
            started += 1
    logger.info(f"Restored and launched {started} persistent 24/7 background agent jobs.")
