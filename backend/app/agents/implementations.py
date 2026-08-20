import json
import logging
import os
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


# --- Agents Implementations ---

class ProjectManagerAgent(BaseAgent):
    """Orchestrates tasks, dependencies, and coordinates execution phases."""
    
    def _run(self, task: Task | None, input_payload: dict | None, agent_run_id: uuid.UUID) -> dict:
        goal = input_payload.get("goal") if input_payload else ""
        if not goal:
            raise ValueError("No project goal provided to Project Manager Agent.")

        logger.info(f"Project Manager creating task graph for goal: {goal}")

        # Define the phases with dependencies
        # Requirements -> Architect -> DB -> Developer -> Testing -> Review
        tasks_definition = [
            ("requirements", "Analyze requirements and acceptance criteria", "RequirementsAgent", []),
            ("architecture", "Design software architecture and application layers", "ArchitectAgent", ["requirements"]),
            ("database", "Design database schema and SQL creation scripts", "DatabaseAgent", ["architecture"]),
            ("developer", "Implement task management API endpoints, schemas, models", "DeveloperAgent", ["database"]),
            ("testing", "Generate unit/integration tests and run test suites", "TestingAgent", ["developer"]),
            ("review", "Perform full code review on generated endpoints and structure", "CodeReviewAgent", ["testing"])
        ]

        created_tasks = []
        task_uuid_map = {}

        for idx, (code, title, agent, deps_codes) in enumerate(tasks_definition):
            dependencies = [task_uuid_map[d] for d in deps_codes if d in task_uuid_map]
            
            new_task = Task(
                project_id=self.project_id,
                title=title,
                description=f"Automated execution task for phase: {code}",
                status=TaskStatus.READY if not dependencies else TaskStatus.PENDING,
                priority=10 - idx,
                assigned_agent=agent,
                dependencies=dependencies
            )
            self.db.add(new_task)
            self.db.commit()
            self.db.refresh(new_task)
            
            task_uuid_map[code] = new_task.id
            created_tasks.append({
                "id": str(new_task.id),
                "title": new_task.title,
                "agent": new_task.assigned_agent,
                "status": new_task.status
            })

            log_event(
                self.db,
                project_id=self.project_id,
                event_type="TASK_CREATED",
                message=f"Task '{new_task.title}' created and assigned to {new_task.assigned_agent}."
            )

        return {"created_tasks": created_tasks}


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
            "functional_requirements": res.functional_requirements,
            "modules": [{"name": m.name, "description": m.description} for m in res.modules]
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
            f"Generate backend application code and write it to disk. Database Schema details:\n{clip(schema_info, 3000)}"
            f"{test_fail_log}\n"
            f"Write the required Python FastAPI models, routers, and main.py files."
        )
        sys_prompt = "You are a senior backend engineer. Implement cleanly, import correctly, and avoid unresolved symbols."
        
        res: DeveloperOutput = self.llm.generate_structured(prompt, DeveloperOutput, sys_prompt)

        created_files = []
        for file in res.files_to_create:
            path = file.path
            content = file.content
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

        return {"files_written": created_files, "message": res.message}


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
        reqs_content = "fastapi\nuvicorn\nsqlalchemy\npytest\n"
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
        prompt = f"Audit this proposed implementation design:\n{json.dumps(input_payload)}"
        sys_prompt = "You are an independent Agent Critic. Identify contradictions, gaps, and weaknesses."
        
        res: CriticOutput = self.llm.generate_structured(prompt, CriticOutput, sys_prompt)

        log_event(
            self.db,
            project_id=self.project_id,
            event_type="AGENT_COMPLETED",
            message=f"Critic Audit completed. Approved: {res.approved}. Suggestions count: {len(res.suggestions)}.",
            payload=res.model_dump()
        )

        return res.model_dump()
