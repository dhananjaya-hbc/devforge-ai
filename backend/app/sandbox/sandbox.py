import logging
import os
import subprocess
from app.core.config import get_settings

logger = logging.getLogger(__name__)


def get_workspace_dir(project_id: str) -> str:
    """Return the absolute path of the project's sandbox directory dynamically."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    workspace_root = os.path.join(base_dir, "sandbox_workspace")
    if not os.path.exists(workspace_root):
        os.makedirs(workspace_root, exist_ok=True)
    project_dir = os.path.join(workspace_root, project_id)
    os.makedirs(project_dir, exist_ok=True)
    return project_dir


def run_sandbox_command(project_id: str, command: str, timeout: int = 90) -> dict:
    """Execute a command in an isolated Docker container, or fallback to subprocess."""
    settings = get_settings()
    local_dir = get_workspace_dir(project_id)
    
    # Try Docker execution first
    try:
        import docker
        client = docker.from_env()
        # Verify docker server is responsive
        client.ping()

        # Resolve host path for mounting
        # inside backend container, /app/sandbox_workspace corresponds to {HOST_WORKSPACE_PATH}/backend/sandbox_workspace
        host_workspace_path = settings.host_workspace_path if hasattr(settings, "host_workspace_path") else "/Users/dhananjaya/Desktop/devforge-ai"
        host_project_path = f"{host_workspace_path}/backend/sandbox_workspace/{project_id}"
        
        logger.info(f"Running docker sandbox for project {project_id} mounting host path {host_project_path}")
        
        # Pull python:3.12-slim if not already present
        try:
            client.images.get("python:3.12-slim")
        except docker.errors.ImageNotFound:
            logger.info("Pulling python:3.12-slim image...")
            client.images.pull("python:3.12-slim")

        # Run command inside isolated container
        container = client.containers.run(
            image="python:3.12-slim",
            command=["sh", "-c", command],
            volumes={host_project_path: {"bind": "/workspace", "mode": "rw"}},
            working_dir="/workspace",
            network_mode="bridge",
            detach=True
        )

        try:
            # Wait for execution to finish
            exit_status = container.wait(timeout=timeout)
            exit_code = exit_status.get("StatusCode", 0)
            stdout = container.logs(stdout=True, stderr=False).decode("utf-8")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8")
        except Exception as exec_err:
            logger.warning(f"Docker container execution timed out/failed: {exec_err}")
            container.kill()
            exit_code = -1
            stdout = ""
            stderr = f"Execution exceeded timeout of {timeout} seconds or failed."
        finally:
            container.remove()

        return {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "method": "docker"
        }

    except Exception as e:
        logger.warning(f"Docker sandbox not available, falling back to subprocess. Error: {e}")
        
        # Subprocess local fallback
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=local_dir,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "method": "subprocess"
            }
        except subprocess.TimeoutExpired:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Execution timed out after {timeout} seconds.",
                "method": "subprocess"
            }
        except Exception as sub_err:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Local subprocess execution failed: {sub_err}",
                "method": "subprocess"
            }
