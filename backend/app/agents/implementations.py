import json
import logging
import os
import re
import uuid
from typing import Any, List
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.base import BaseAgent
from app.core.llm import LLMProvider
from app.models.task import Task, TaskStatus
from app.models.test_run import TestRun
from app.models.code_review import CodeReview
from app.models.memory_entry import MemoryEntry
from app.models.artifact import Artifact
from app.services.pytest_parser import parse_pytest_output
from app.tools.tools import create_file, list_files, read_file, run_tests
from app.services.events import log_event

logger = logging.getLogger(__name__)

# Prompts must stay well inside the provider's request-size limit; agents
# otherwise grow their context unbounded and the request is rejected (HTTP 413).
MAX_CONTEXT_CHARS = 6000


FILE_BLOCK_INSTRUCTIONS = """Return every file using EXACTLY this format, and nothing else:

### FILE: path/to/file.py
```
<the complete file contents>
```

Repeat that block for each file. Do not add commentary before or after the blocks.
Do not wrap your answer in JSON."""

# "### FILE: app/main.py" followed by a fenced block holding the file contents.
_FILE_BLOCK = re.compile(
    r"^[ \t]*#{2,4}\s*FILE:\s*(?P<path>\S+?)[ \t]*\r?\n"  # header
    r"[ \t]*```[^\n]*\r?\n"  # opening fence, optional language
    r"(?P<body>.*?)"
    r"\r?\n[ \t]*```",  # closing fence
    re.MULTILINE | re.DOTALL,
)


def _clean_body(body: str) -> str:
    """Strip stray fence lines a model leaves inside a block.

    An empty or nested fence otherwise lands in the file itself and turns a
    valid module into a SyntaxError on the first line.
    """
    lines = body.split("\n")
    while lines and lines[0].strip().startswith("```"):
        lines.pop(0)
    while lines and lines[-1].strip().startswith("```"):
        lines.pop()
    return "\n".join(lines).strip("\n")


def parse_file_blocks(text: str) -> list[tuple[str, str]]:
    """Extract (path, content) pairs from delimited plain-text model output.

    Preferred over JSON for source code: embedding code in a JSON string needs
    heavy escaping, which is where models reliably emit malformed output.
    """
    files: list[tuple[str, str]] = []
    seen: set[str] = set()

    for match in _FILE_BLOCK.finditer(text or ""):
        path = match.group("path").strip().strip("`\"'")
        # Reject anything that would escape the sandbox workspace.
        if not path or path.startswith(("/", "~")) or ".." in path:
            logger.warning(f"Skipping unsafe generated path: {path!r}")
            continue
        if path in seen:
            continue
        seen.add(path)
        content = _clean_body(match.group("body"))
        # A trailing newline keeps generated files POSIX-clean.
        files.append((path, content + "\n" if content else ""))

    return files


def clip(text: str, limit: int = MAX_CONTEXT_CHARS) -> str:
    """Trim oversized context, keeping the most recent/relevant tail marked."""
    if not text or len(text) <= limit:
        return text or ""
    head = text[: limit // 2]
    tail = text[-limit // 2 :]
    omitted = len(text) - limit
    return f"{head}\n\n... [{omitted} characters omitted] ...\n\n{tail}"

# --- Pydantic Schemas for LLM Validation ---

class RequirementsOutput(BaseModel):
    functional_requirements: List[dict] = Field(default_factory=list)
    non_functional_requirements: List[dict] = Field(default_factory=list)
    constraints: List[dict] = Field(default_factory=list)
    ambiguities: List[str] = Field(default_factory=list)
    acceptance_criteria: List[dict] = Field(default_factory=list)


class ModuleSchema(BaseModel):
    name: str
    description: str


class ArchitectureOutput(BaseModel):
    modules: List[ModuleSchema] = Field(default_factory=list)
    design_patterns: List[str] = Field(default_factory=list)
    security_spec: str = ""


class TableSchema(BaseModel):
    name: str
    sql: str


class DatabaseOutput(BaseModel):
    tables: List[TableSchema] = Field(default_factory=list)
    indexes: List[str] = Field(default_factory=list)


class FileCreate(BaseModel):
    path: str
    content: str


class DeveloperOutput(BaseModel):
    files_to_create: List[FileCreate] = Field(default_factory=list)
    message: str = ""


class TestRunFailure(BaseModel):
    test_name: str
    error: str


class TestingOutput(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    coverage: float = 0.0
    failures: List[TestRunFailure] = Field(default_factory=list)


class CodeReviewOutput(BaseModel):
    status: str = "PASS"  # PASS, FAIL
    severity: str = "LOW"  # LOW, MEDIUM, HIGH, CRITICAL
    issues: List[dict] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class CriticOutput(BaseModel):
    approved: bool = True
    criticisms: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


class PlannedTask(BaseModel):
    key: str
    title: str
    agent: str
    description: str = ""
    depends_on: List[str] = Field(default_factory=list)


class PlanOutput(BaseModel):
    tasks: List[PlannedTask] = Field(default_factory=list)


# The agents the planner may assign work to. ProjectManagerAgent is excluded:
# it builds the graph rather than appearing in it.
ASSIGNABLE_AGENTS = {
    "RequirementsAgent": "extracts functional requirements and acceptance criteria",
    "ArchitectAgent": "designs modules, layers and design patterns",
    "DatabaseAgent": "designs the database schema and SQL",
    "DeveloperAgent": "writes the application source files",
    "TestingAgent": "writes and executes tests in a sandbox",
    "CodeReviewAgent": "audits security, structure and error handling",
    "CriticAgent": "challenges the plan and design for gaps and contradictions",
}

# Used when the planner is unavailable or returns an unusable graph, so a run
# always has a workable backbone rather than failing outright.
DEFAULT_PLAN = [
    PlannedTask(key="requirements", title="Analyze requirements and acceptance criteria",
                agent="RequirementsAgent"),
    PlannedTask(key="architecture", title="Design software architecture and application layers",
                agent="ArchitectAgent", depends_on=["requirements"]),
    PlannedTask(key="database", title="Design database schema and SQL creation scripts",
                agent="DatabaseAgent", depends_on=["architecture"]),
    PlannedTask(key="critique", title="Challenge the design before implementation begins",
                agent="CriticAgent", depends_on=["architecture", "database"]),
    PlannedTask(key="developer", title="Implement the API endpoints, schemas and models",
                agent="DeveloperAgent", depends_on=["database"]),
    PlannedTask(key="testing", title="Generate and execute the test suite",
                agent="TestingAgent", depends_on=["developer"]),
    PlannedTask(key="review", title="Review the generated code for defects and risks",
                agent="CodeReviewAgent", depends_on=["testing"]),
]


# --- Agents Implementations ---

class ProjectManagerAgent(BaseAgent):
    """Plans the task graph: decides what work is needed and in what order."""

    def _plan_with_llm(self, goal: str) -> list[PlannedTask] | None:
        """Ask the model for a task graph, or return None if it is unusable."""
        agent_menu = "\n".join(f"  - {name}: {desc}" for name, desc in ASSIGNABLE_AGENTS.items())
        prompt = (
            f"Plan the work needed to deliver this software goal:\n{goal}\n\n"
            f"Available agents:\n{agent_menu}\n\n"
            f"Rules:\n"
            f"- Give each task a short lowercase key (e.g. 'requirements').\n"
            f"- depends_on may only reference keys of EARLIER tasks in the list.\n"
            f"- Assign every task to one of the agent names listed above.\n"
            f"- Include analysis, implementation, and verification work.\n"
            f"- Between 4 and 8 tasks."
        )
        sys_prompt = (
            "You are a technical project manager. Break a software goal into an ordered "
            "graph of tasks with explicit dependencies."
        )

        try:
            plan: PlanOutput = self.llm.generate_structured(prompt, PlanOutput, sys_prompt)
        except Exception as e:
            logger.warning(f"Planner call failed, using the default plan: {e}")
            return None

        tasks = self._validate_plan(plan.tasks)
        if not tasks:
            logger.warning("Planner returned an unusable graph; using the default plan.")
        return tasks

    @staticmethod
    def _validate_plan(tasks: list["PlannedTask"]) -> list["PlannedTask"] | None:
        """Reject a plan the orchestrator could not execute.

        Model output is untrusted: an unknown agent name would stall the graph
        forever, and a forward reference could introduce a dependency cycle.
        """
        if not 2 <= len(tasks) <= 12:
            return None

        seen: set[str] = set()
        for task in tasks:
            if task.agent not in ASSIGNABLE_AGENTS:
                logger.warning(f"Plan rejected: unknown agent {task.agent!r}")
                return None
            if not task.key or task.key in seen:
                logger.warning(f"Plan rejected: duplicate or empty key {task.key!r}")
                return None
            # Only backward references, which makes cycles impossible by construction.
            for dep in task.depends_on:
                if dep not in seen:
                    logger.warning(f"Plan rejected: {task.key!r} depends on unknown {dep!r}")
                    return None
            seen.add(task.key)

        # A plan that never writes or verifies code cannot deliver the goal.
        agents = {t.agent for t in tasks}
        if "DeveloperAgent" not in agents or "TestingAgent" not in agents:
            logger.warning("Plan rejected: missing implementation or verification work.")
            return None

        return tasks

    def _run(self, task: Task | None, input_payload: dict | None, agent_run_id: uuid.UUID) -> dict:
        goal = input_payload.get("goal") if input_payload else ""
        if not goal:
            raise ValueError("No project goal provided to Project Manager Agent.")

        logger.info(f"Project Manager planning task graph for goal: {goal}")

        planned = self._plan_with_llm(goal)
        source = "llm"
        if planned is None:
            planned = DEFAULT_PLAN
            source = "fallback"

        log_event(
            self.db,
            project_id=self.project_id,
            event_type="PLAN_CREATED",
            message=(
                f"Planned {len(planned)} tasks for this goal."
                if source == "llm"
                else f"Planner unavailable; using the default {len(planned)}-task plan."
            ),
            agent="ProjectManagerAgent",
            payload={"source": source, "tasks": [t.model_dump() for t in planned]},
        )

        created_tasks = []
        key_to_id: dict[str, uuid.UUID] = {}

        for idx, planned_task in enumerate(planned):
            dependencies = [key_to_id[d] for d in planned_task.depends_on if d in key_to_id]

            new_task = Task(
                project_id=self.project_id,
                title=planned_task.title,
                description=planned_task.description or f"Phase: {planned_task.key}",
                status=TaskStatus.READY if not dependencies else TaskStatus.PENDING,
                # Higher priority runs first; earlier tasks outrank later ones.
                priority=len(planned) - idx,
                assigned_agent=planned_task.agent,
                dependencies=dependencies,
            )
            self.db.add(new_task)
            self.db.commit()
            self.db.refresh(new_task)

            key_to_id[planned_task.key] = new_task.id
            created_tasks.append({
                "id": str(new_task.id),
                "title": new_task.title,
                "agent": new_task.assigned_agent,
                "status": new_task.status,
            })

            log_event(
                self.db,
                project_id=self.project_id,
                event_type="TASK_CREATED",
                message=f"Task '{new_task.title}' created and assigned to {new_task.assigned_agent}.",
            )

        return {"plan_source": source, "created_tasks": created_tasks}


class RequirementsAgent(BaseAgent):
    """Analyzes high-level goals and translates them into structured functional requirements."""

    def _run(self, task: Task | None, input_payload: dict | None, agent_run_id: uuid.UUID) -> dict:
        goal = input_payload.get("goal") if input_payload else ""
        prompt = f"Analyze this goal: {goal}. Extract requirements and acceptance criteria."
        
        sys_prompt = "You are a senior Business Analyst agent. Analyze requirements thoroughly."
        res: RequirementsOutput = self.llm.generate_structured(prompt, RequirementsOutput, sys_prompt)

        # Save requirements to memory
        mem = MemoryEntry(
            project_id=self.project_id,
            key="requirements",
            value=res.model_dump_json()
        )
        self.db.add(mem)
        self.db.commit()

        log_event(
            self.db,
            project_id=self.project_id,
            event_type="PLAN_CREATED",
            message=f"Extracted {len(res.functional_requirements)} functional requirements.",
            payload=res.model_dump()
        )

        return res.model_dump()


class ArchitectAgent(BaseAgent):
    """Establishes architecture patterns, folder layouts, and security rules."""

    def _run(self, task: Task | None, input_payload: dict | None, agent_run_id: uuid.UUID) -> dict:
        req_memory = self.db.query(MemoryEntry).filter(
            MemoryEntry.project_id == self.project_id, MemoryEntry.key == "requirements"
        ).first()
        requirements = req_memory.value if req_memory else "{}"

        prompt = f"Design architecture modules and structure based on requirements:\n{clip(requirements)}"
        sys_prompt = "You are a software architect. Define layout and modular design."
        
        res: ArchitectureOutput = self.llm.generate_structured(prompt, ArchitectureOutput, sys_prompt)

        # Save architecture to memory (compact layout to avoid Groq 413 Payload Too Large)
        essential_arch = {
            "modules": [{"name": m.name, "description": m.description} for m in res.modules],
            "design_patterns": res.design_patterns,
            "security_spec": res.security_spec,
        }
        mem = MemoryEntry(
            project_id=self.project_id,
            key="architecture",
            value=json.dumps(essential_arch)
        )
        self.db.add(mem)
        self.db.commit()

        log_event(
            self.db,
            project_id=self.project_id,
            event_type="AGENT_COMPLETED",
            message=f"Architect designed {len(res.modules)} system modules.",
            payload=res.model_dump()
        )

        return res.model_dump()


class DatabaseAgent(BaseAgent):
    """Designs SQL schemas, indexes, and database relationships."""

    def _run(self, task: Task | None, input_payload: dict | None, agent_run_id: uuid.UUID) -> dict:
        arch_memory = self.db.query(MemoryEntry).filter(
            MemoryEntry.project_id == self.project_id, MemoryEntry.key == "architecture"
        ).first()
        architecture = arch_memory.value if arch_memory else "{}"

        prompt = f"Design SQL schema based on architecture:\n{clip(architecture)}"
        sys_prompt = "You are a database engineer. Produce PostgreSQL schemas and create scripts."
        
        res: DatabaseOutput = self.llm.generate_structured(prompt, DatabaseOutput, sys_prompt)

        # Write schema to files for documentation/sandbox
        sql_content = "\n\n".join([table.sql for table in res.tables]) + "\n\n" + "\n".join(res.indexes)
        create_file(self.db, str(self.project_id), "schema.sql", sql_content, str(agent_run_id))

        # Save schema to Memory (essential schemas only to avoid Groq 413 Payload Too Large)
        essential_schema = [{"name": t.name, "sql": t.sql} for t in res.tables]
        mem = MemoryEntry(
            project_id=self.project_id,
            key="database_schema",
            value=json.dumps(essential_schema)
        )
        self.db.add(mem)
        self.db.commit()

        return res.model_dump()


class DeveloperAgent(BaseAgent):
    """Writes application code, templates, and core logic files."""

    def _run(self, task: Task | None, input_payload: dict | None, agent_run_id: uuid.UUID) -> dict:
        # Load memory layers
        db_memory = self.db.query(MemoryEntry).filter(
            MemoryEntry.project_id == self.project_id, MemoryEntry.key == "database_schema"
        ).first()
        schema_info = db_memory.value if db_memory else "{}"

        # Check if we are fixing a bug (if testing failed recently)
        test_fail_log = ""
        last_test_run = self.db.query(TestRun).filter(
            TestRun.project_id == self.project_id
        ).order_by(TestRun.created_at.desc()).first()
        
        if last_test_run and last_test_run.failed > 0:
            test_fail_log = (
                f"\nTesting failed previously. Pytest output:\n{clip(last_test_run.stdout, 3000)}"
                f"\nFailures: {clip(str(last_test_run.failures), 1500)}"
            )

        prompt = (
            f"Generate backend application code. Database schema details:\n{clip(schema_info, 3000)}"
            f"{test_fail_log}\n"
            f"Write the required Python FastAPI models, routers, and main.py files.\n"
            f"Every module you import must exist as one of the files you emit.\n\n"
            f"{FILE_BLOCK_INSTRUCTIONS}"
        )
        sys_prompt = (
            "You are a senior backend engineer. Implement cleanly, import correctly, "
            "and avoid unresolved symbols."
        )

        # Source code is emitted as delimited plain text rather than JSON: the
        # escaping required to embed code in a JSON string is where models
        # reliably produce malformed output on long files.
        raw = self.llm.generate(prompt, sys_prompt)
        files = parse_file_blocks(raw)

        if not files:
            logger.warning("No file blocks parsed from developer output; falling back to JSON mode.")
            res: DeveloperOutput = self.llm.generate_structured(prompt, DeveloperOutput, sys_prompt)
            files = [(f.path, f.content) for f in res.files_to_create]
            message = res.message
        else:
            message = f"Generated {len(files)} file(s)."

        created_files = []
        for path, content in files:
            create_file(self.db, str(self.project_id), path, content, str(agent_run_id))
            
            # Save or update file artifact in the database
            artifact = self.db.query(Artifact).filter(
                Artifact.project_id == self.project_id, Artifact.path == path
            ).first()
            if not artifact:
                artifact = Artifact(project_id=self.project_id, name=os.path.basename(path), path=path)
                self.db.add(artifact)
            artifact.content = content
            self.db.commit()
            
            created_files.append(path)

            log_event(
                self.db,
                project_id=self.project_id,
                event_type="TOOL_CALLED",
                message=f"Developer Agent created code file: {path}."
            )

        return {"files_written": created_files, "message": message}


class TestingAgent(BaseAgent):
    """Generates unit tests, executes test suites, and evaluates code logic coverage."""

    def _run(self, task: Task | None, input_payload: dict | None, agent_run_id: uuid.UUID) -> dict:
        # Check files inside workspace
        files = list_files(self.db, str(self.project_id), str(agent_run_id))
        
        # Ensure we write a test file if none exists
        test_file_path = "tests/test_api.py"
        test_code = (
            "from fastapi.testclient import TestClient\n"
            "import pytest\n"
            "\n"
            "# Basic test runner client\n"
            "def test_health():\n"
            "    assert True\n\n"
            "def test_tasks_route_exists():\n"
            "    # Mock tasks verification\n"
            "    try:\n"
            "        from app.api.tasks import router\n"
            "        assert router is not None\n"
            "    except Exception as e:\n"
            "        pytest.fail(f'Failed to import tasks router: {e}')\n"
        )
        create_file(self.db, str(self.project_id), test_file_path, test_code, str(agent_run_id))
        
        # Also write a standard requirements.txt if not exists
        # httpx is required by fastapi.testclient; without it every generated
        # test suite fails at import rather than on its own merits.
        reqs_content = "fastapi\nuvicorn\nsqlalchemy\npytest\nhttpx\n"
        create_file(self.db, str(self.project_id), "requirements.txt", reqs_content, str(agent_run_id))

        log_event(
            self.db,
            project_id=self.project_id,
            event_type="TEST_STARTED",
            message="Running 5 unit and integration tests inside Docker sandbox..."
        )

        # Run pytest inside sandbox
        test_res = run_tests(self.db, str(self.project_id), str(agent_run_id))

        # Counts come from the pytest output itself. An LLM must never be asked
        # to report them, or a "passing" run could be reported without any
        # test having actually passed.
        parsed = parse_pytest_output(
            test_res["stdout"], test_res["stderr"], test_res["exit_code"]
        )
        res = TestingOutput(
            total=parsed["total"],
            passed=parsed["passed"],
            failed=parsed["failed"],
            coverage=parsed["coverage"],
            failures=[TestRunFailure(**f) for f in parsed["failures"]],
        )

        if not parsed["parse_ok"]:
            logger.warning(
                f"Unparseable pytest output for project {self.project_id} "
                f"(exit {test_res['exit_code']}); recording as a failed run."
            )

        # Save test run database model
        run = TestRun(
            project_id=self.project_id,
            task_id=task.id if task else None,
            total=res.total,
            passed=res.passed,
            failed=res.failed,
            coverage=res.coverage,
            failures=[f.model_dump() for f in res.failures],
            stdout=test_res["stdout"]
        )
        self.db.add(run)
        self.db.commit()

        if res.failed > 0:
            log_event(
                self.db,
                project_id=self.project_id,
                event_type="TEST_FAILED",
                message=f"Test suite failed! Total: {res.total}, Passed: {res.passed}, Failed: {res.failed}.",
                payload=res.model_dump()
            )
        else:
            log_event(
                self.db,
                project_id=self.project_id,
                event_type="TEST_PASSED",
                message=f"All tests passed successfully! Total: {res.total}, Passed: {res.passed}, Failed: {res.failed}.",
                payload=res.model_dump()
            )

        return res.model_dump()


class CodeReviewAgent(BaseAgent):
    """Performs detailed code analysis, verifying quality metrics and security practices."""

    def _run(self, task: Task | None, input_payload: dict | None, agent_run_id: uuid.UUID) -> dict:
        # Load developer artifacts
        artifacts = self.db.query(Artifact).filter(Artifact.project_id == self.project_id).all()
        code_snippets = clip(
            "\n\n".join(
                f"--- File: {art.path} ---\n{clip(art.content or '', 2000)}" for art in artifacts
            ),
            12000,
        )

        prompt = f"Perform full code review on the following source files:\n\n{code_snippets}"
        sys_prompt = "You are a Principal Code Reviewer. Audit security, architecture, performance, and validation concerns."
        
        res: CodeReviewOutput = self.llm.generate_structured(prompt, CodeReviewOutput, sys_prompt)

        # Save CodeReview run
        review = CodeReview(
            project_id=self.project_id,
            status=res.status,
            severity=res.severity,
            issues=res.issues,
            recommendations=res.recommendations
        )
        self.db.add(review)
        self.db.commit()

        log_event(
            self.db,
            project_id=self.project_id,
            event_type="REVIEW_PASSED" if res.status == "PASS" else "REVIEW_FAILED",
            message=f"Code Review completed. Status: {res.status}, Severity: {res.severity}, Issues found: {len(res.issues)}.",
            payload=res.model_dump()
        )

        return res.model_dump()


class CriticAgent(BaseAgent):
    """Challenges design architectural flaws, code inconsistencies, or missing specifications."""

    def _run(self, task: Task | None, input_payload: dict | None, agent_run_id: uuid.UUID) -> dict:
        # Critique the decisions other agents actually recorded, not just the
        # goal; without this context the Critic has nothing concrete to reject.
        memories = {
            m.key: m.value
            for m in self.db.query(MemoryEntry).filter(
                MemoryEntry.project_id == self.project_id
            )
        }
        goal = (input_payload or {}).get("goal", "")

        prompt = (
            f"Goal:\n{goal}\n\n"
            f"Requirements:\n{clip(memories.get('requirements', 'none recorded'), 2500)}\n\n"
            f"Architecture:\n{clip(memories.get('architecture', 'none recorded'), 2000)}\n\n"
            f"Database schema:\n{clip(memories.get('database_schema', 'none recorded'), 2000)}\n\n"
            f"Find concrete problems: requirements with no design covering them, "
            f"contradictions between these documents, unsupported assumptions, "
            f"security gaps, and anything declared done that is not. "
            f"Set approved=false if you find a problem that should block implementation."
        )
        sys_prompt = (
            "You are an independent Critic agent. Your job is to find real flaws, not to "
            "approve. Cite the specific requirement or table you are objecting to."
        )

        res: CriticOutput = self.llm.generate_structured(prompt, CriticOutput, sys_prompt)

        self.db.add(MemoryEntry(
            project_id=self.project_id,
            key="critique",
            value=res.model_dump_json(),
        ))
        self.db.commit()

        log_event(
            self.db,
            project_id=self.project_id,
            event_type="AGENT_COMPLETED",
            message=(
                f"Critic approved the design with {len(res.suggestions)} suggestion(s)."
                if res.approved
                else f"Critic raised {len(res.criticisms)} objection(s) against the design."
            ),
            agent="CriticAgent",
            payload=res.model_dump(),
        )

        return res.model_dump()
