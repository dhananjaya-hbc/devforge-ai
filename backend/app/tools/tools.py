import logging
import os
import time
from sqlalchemy.orm import Session

from app.models.tool_call import ToolCall
from app.sandbox.sandbox import get_workspace_dir, run_sandbox_command

logger = logging.getLogger(__name__)


def validate_path(project_id: str, filepath: str) -> str:
    """Validate that filepath is strictly within the project's sandbox workspace."""
    base_dir = os.path.abspath(get_workspace_dir(project_id))
    target_path = os.path.abspath(os.path.join(base_dir, filepath))
    if not target_path.startswith(base_dir):
        raise PermissionError(f"Access Denied: Path traversal attempt blocked for path: {filepath}")
    return target_path


def log_tool_call(
    db: Session,
    project_id: str,
    agent_run_id: str | None,
    tool_name: str,
    input_payload: dict,
    output_payload: str,
    status: str,
    duration_ms: float
) -> ToolCall:
    """Helper to write tool execution telemetry directly to the database."""
    tool_call = ToolCall(
        project_id=project_id,
        agent_run_id=agent_run_id,
        tool_name=tool_name,
        input_payload=input_payload,
        output_payload=output_payload,
        status=status,
        duration_ms=duration_ms
    )
    db.add(tool_call)
    db.commit()
    db.refresh(tool_call)
    return tool_call


def list_files(db: Session, project_id: str, agent_run_id: str | None = None) -> list[str]:
    start_time = time.time()
    workspace = get_workspace_dir(project_id)
    files = []
    
    try:
        for root, _, filenames in os.walk(workspace):
            for filename in filenames:
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, workspace)
                files.append(rel_path)
        status = "SUCCESS"
        output = f"Found {len(files)} files."
    except Exception as e:
        status = "FAILED"
        output = str(e)
        logger.error(f"list_files tool error: {e}")

    log_tool_call(
        db, project_id, agent_run_id, "list_files",
        {}, output, status, (time.time() - start_time) * 1000
    )
    return files


def read_file(db: Session, project_id: str, filepath: str, agent_run_id: str | None = None) -> str:
    start_time = time.time()
    try:
        abs_path = validate_path(project_id, filepath)
        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"File not found: {filepath}")
            
        with open(abs_path, "r", encoding="utf-8") as f:
            content = f.read()
        status = "SUCCESS"
        output_log = f"Successfully read {len(content)} characters."
    except Exception as e:
        status = "FAILED"
        content = f"Error: {e}"
        output_log = content
        logger.error(f"read_file tool error: {e}")

    log_tool_call(
        db, project_id, agent_run_id, "read_file",
        {"filepath": filepath}, output_log, status, (time.time() - start_time) * 1000
    )
    return content


def create_file(db: Session, project_id: str, filepath: str, content: str, agent_run_id: str | None = None) -> str:
    start_time = time.time()
    try:
        abs_path = validate_path(project_id, filepath)
        # Create directories if they don't exist
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        status = "SUCCESS"
        output = f"File created/overwritten at {filepath} with {len(content)} characters."
    except Exception as e:
        status = "FAILED"
        output = f"Error: {e}"
        logger.error(f"create_file tool error: {e}")

    log_tool_call(
        db, project_id, agent_run_id, "create_file",
        {"filepath": filepath, "content_length": len(content)}, output, status, (time.time() - start_time) * 1000
    )
    return output


def delete_file(db: Session, project_id: str, filepath: str, agent_run_id: str | None = None) -> str:
    start_time = time.time()
    try:
        abs_path = validate_path(project_id, filepath)
        if os.path.exists(abs_path):
            os.remove(abs_path)
            status = "SUCCESS"
            output = f"Successfully deleted file: {filepath}"
        else:
            status = "FAILED"
            output = f"File does not exist: {filepath}"
    except Exception as e:
        status = "FAILED"
        output = f"Error: {e}"
        logger.error(f"delete_file tool error: {e}")

    log_tool_call(
        db, project_id, agent_run_id, "delete_file",
        {"filepath": filepath}, output, status, (time.time() - start_time) * 1000
    )
    return output


def search_code(db: Session, project_id: str, query: str, agent_run_id: str | None = None) -> list[dict]:
    start_time = time.time()
    workspace = get_workspace_dir(project_id)
    matches = []
    
    try:
        for root, _, filenames in os.walk(workspace):
            for filename in filenames:
                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, workspace)
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                    for idx, line in enumerate(lines):
                        if query.lower() in line.lower():
                            matches.append({
                                "filepath": rel_path,
                                "line_number": idx + 1,
                                "match": line.strip()
                            })
                except Exception:
                    pass # Ignore binary/unread files
        status = "SUCCESS"
        output_log = f"Found {len(matches)} matches."
    except Exception as e:
        status = "FAILED"
        output_log = str(e)
        logger.error(f"search_code tool error: {e}")

    log_tool_call(
        db, project_id, agent_run_id, "search_code",
        {"query": query}, output_log, status, (time.time() - start_time) * 1000
    )
    return matches[:50] # Return top 50 matches


def install_dependency(db: Session, project_id: str, package_name: str, agent_run_id: str | None = None) -> str:
    start_time = time.time()
    command = f"pip install {package_name}"
    res = run_sandbox_command(project_id, command)
    
    status = "SUCCESS" if res["exit_code"] == 0 else "FAILED"
    output = f"stdout:\n{res['stdout']}\n\nstderr:\n{res['stderr']}"
    
    log_tool_call(
        db, project_id, agent_run_id, "install_dependency",
        {"package_name": package_name}, output, status, (time.time() - start_time) * 1000
    )
    return output


def run_tests(db: Session, project_id: str, agent_run_id: str | None = None) -> dict:
    start_time = time.time()
    # The sandbox image is bare Python, so pytest and the generated project's
    # own dependencies must be installed before the suite can run at all.
    command = (
        # httpx backs fastapi.testclient. Some starlette builds want the httpx2
        # distribution instead, so try it but never let its absence stop the run.
        "python -m pip install -q --disable-pip-version-check pytest httpx >/dev/null 2>&1; "
        "python -m pip install -q --disable-pip-version-check httpx2 >/dev/null 2>&1 || true; "
        "if [ -f requirements.txt ]; then "
        "python -m pip install -q --disable-pip-version-check -r requirements.txt "
        ">/dev/null 2>&1 || true; fi; "
        "python -m pytest --tb=short -q"
    )
    res = run_sandbox_command(project_id, command, timeout=300)
    
    status = "SUCCESS" if res["exit_code"] == 0 else "FAILED"
    output = f"stdout:\n{res['stdout']}\n\nstderr:\n{res['stderr']}"
    
    # Save a compact string summary as the ToolCall output
    summary = f"Exit code: {res['exit_code']}. "
    if "passed" in res["stdout"].lower() or "failed" in res["stdout"].lower():
        summary += res["stdout"].split("\n")[-2] if len(res["stdout"].split("\n")) > 1 else ""
    
    log_tool_call(
        db, project_id, agent_run_id, "run_tests",
        {}, summary or output[:1000], status, (time.time() - start_time) * 1000
    )
    return res


def run_command(db: Session, project_id: str, command: str, agent_run_id: str | None = None) -> dict:
    start_time = time.time()
    # Basic protection against running host-affecting commands
    blocked_patterns = ["rm -rf /", "shutdown", "reboot", "poweroff"]
    if any(p in command for p in blocked_patterns):
        output = "Command rejected: forbidden pattern."
        log_tool_call(
            db, project_id, agent_run_id, "run_command",
            {"command": command}, output, "FAILED", 0
        )
        return {"exit_code": -1, "stdout": "", "stderr": output}

    res = run_sandbox_command(project_id, command)
    status = "SUCCESS" if res["exit_code"] == 0 else "FAILED"
    output = f"stdout:\n{res['stdout']}\n\nstderr:\n{res['stderr']}"
    
    log_tool_call(
        db, project_id, agent_run_id, "run_command",
        {"command": command}, output[:1000], status, (time.time() - start_time) * 1000
    )
    return res
