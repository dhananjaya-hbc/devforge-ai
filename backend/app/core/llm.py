import abc
import json
import logging
import re
from collections.abc import Generator
from typing import Any, Type

import boto3
import httpx
from pydantic import BaseModel

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        """Generate text from prompt."""
        pass

    @abc.abstractmethod
    def stream(self, prompt: str, system_prompt: str | None = None) -> Generator[str, None, None]:
        """Stream response generator."""
        pass

    def generate_structured(
        self, prompt: str, response_model: Type[BaseModel], system_prompt: str | None = None
    ) -> Any:
        """Request JSON structured output matching response_model."""
        schema_json = json.dumps(response_model.model_json_schema())
        enhanced_prompt = (
            f"{prompt}\n\n"
            f"CRITICAL: You MUST respond ONLY with a raw JSON object matching the following schema. "
            f"Do not include conversational filler, markdown formatting (do not wrap in ```json or ```), "
            f"or explanations.\n\n"
            f"JSON Schema:\n{schema_json}"
        )

        response_text = self.generate(enhanced_prompt, system_prompt)
        cleaned_text = self._clean_json_response(response_text)
        try:
            return response_model.model_validate_json(cleaned_text)
        except Exception as e:
            logger.error(f"Failed to parse structured output. Text: {cleaned_text}. Error: {e}")
            # Fallback regex parsing if needed
            json_match = re.search(r"\{.*\}", cleaned_text, re.DOTALL)
            if json_match:
                try:
                    return response_model.model_validate_json(json_match.group(0))
                except Exception as inner_e:
                    logger.error(f"Fallback regex parse failed: {inner_e}")
            raise e

    def _clean_json_response(self, text: str) -> str:
        """Strip markdown ticks and conversational text outside JSON block."""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3"):
        self.base_url = base_url
        self.model = model

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        }
        if system_prompt:
            payload["system"] = system_prompt

        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                return response.json().get("response", "")
        except Exception as e:
            logger.error(f"Ollama generate error: {e}")
            raise RuntimeError(f"Ollama connection failed: {e}")

    def stream(self, prompt: str, system_prompt: str | None = None) -> Generator[str, None, None]:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": True,
            "options": {"temperature": 0.2},
        }
        if system_prompt:
            payload["system"] = system_prompt

        try:
            with httpx.Client(timeout=120.0) as client:
                with client.stream("POST", url, json=payload) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if line:
                            data = json.loads(line)
                            yield data.get("response", "")
        except Exception as e:
            logger.error(f"Ollama stream error: {e}")
            raise RuntimeError(f"Ollama streaming failed: {e}")


class BedrockProvider(LLMProvider):
    def __init__(self, region_name: str = "us-east-1", model_id: str = "meta.llama3-1-70b-instruct-v1:0"):
        self.model_id = model_id
        # AWS credentials will be picked up automatically from env/role credentials
        self.client = boto3.client("bedrock-runtime", region_name=region_name)

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        # Llama 3 prompt format
        formatted_prompt = ""
        if system_prompt:
            formatted_prompt += f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system_prompt}<|eot_id|>"
        else:
            formatted_prompt += "<|begin_of_text|>"
        formatted_prompt += f"<|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"

        body = json.dumps({
            "prompt": formatted_prompt,
            "max_gen_len": 2048,
            "temperature": 0.2,
            "top_p": 0.9,
        })

        try:
            response = self.client.invoke_model(
                body=body,
                modelId=self.model_id,
                accept="application/json",
                contentType="application/json"
            )
            response_body = json.loads(response.get("body").read())
            return response_body.get("generation", "")
        except Exception as e:
            logger.error(f"AWS Bedrock generate error: {e}")
            raise RuntimeError(f"AWS Bedrock invocation failed: {e}")

    def stream(self, prompt: str, system_prompt: str | None = None) -> Generator[str, None, None]:
        # Simple non-streamed fallback for bedrock streaming for simplicity
        yield self.generate(prompt, system_prompt)


class SimulatorProvider(LLMProvider):
    """Simulator provider pre-programmed with high-fidelity responses for DevForge AI demo goals."""
    
    def __init__(self):
        # Keeps track of developer coding attempts to simulate a code bug -> fail -> fix loop
        self.developer_attempts = 0

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        # 1. PM/Requirements Extraction Prompt
        if "ambiguities" in prompt.lower() or "functional_requirements" in prompt.lower():
            return json.dumps({
                "functional_requirements": [
                    {"id": "FR-1", "description": "User registration with email and password"},
                    {"id": "FR-2", "description": "User login generating a JWT token"},
                    {"id": "FR-3", "description": "Retrieve tasks for the logged in user"},
                    {"id": "FR-4", "description": "Create a new task with title, description, and status"},
                    {"id": "FR-5", "description": "Update an existing task status, title, or description"},
                    {"id": "FR-6", "description": "Delete a task by ID"}
                ],
                "non_functional_requirements": [
                    {"id": "NFR-1", "description": "API responses under 200ms"},
                    {"id": "NFR-2", "description": "Password hashing using bcrypt"},
                    {"id": "NFR-3", "description": "JWT-based authentication headers"}
                ],
                "constraints": [
                    {"id": "CON-1", "description": "Database must be PostgreSQL"},
                    {"id": "CON-2", "description": "Backend framework must be FastAPI"}
                ],
                "ambiguities": [],
                "acceptance_criteria": [
                    {"id": "AC-1", "description": "Registering returns 201 Created and user metadata"},
                    {"id": "AC-2", "description": "Creating task without Auth returns 401 Unauthorized"}
                ]
            })

        # 2. Architect Agent Prompt
        elif "architecture" in prompt.lower() or "modules" in prompt.lower():
            return json.dumps({
                "modules": [
                    {"name": "app/main.py", "description": "Main entry point for FastAPI"},
                    {"name": "app/core/config.py", "description": "Configuration settings"},
                    {"name": "app/core/database.py", "description": "Database engine and session"},
                    {"name": "app/models/user.py", "description": "User SQLAlchemy entity"},
                    {"name": "app/models/task.py", "description": "Task SQLAlchemy entity"},
                    {"name": "app/api/auth.py", "description": "Authentication endpoints"},
                    {"name": "app/api/tasks.py", "description": "Tasks management endpoints"},
                    {"name": "app/schemas/user.py", "description": "User Pydantic validations"},
                    {"name": "app/schemas/task.py", "description": "Task Pydantic validations"}
                ],
                "design_patterns": ["Repository pattern for database access", "Dependency Injection for DB sessions"],
                "security_spec": "BCrypt password hashing, JWT HS256 tokens"
            })

        # 3. Database Agent Prompt
        elif "schema" in prompt.lower() or "postgresql schema" in prompt.lower():
            return json.dumps({
                "tables": [
                    {
                        "name": "users",
                        "sql": "CREATE TABLE users (id UUID PRIMARY KEY, email VARCHAR(255) UNIQUE NOT NULL, hashed_password VARCHAR(255) NOT NULL, created_at TIMESTAMP DEFAULT NOW());"
                    },
                    {
                        "name": "tasks",
                        "sql": "CREATE TABLE tasks (id UUID PRIMARY KEY, user_id UUID REFERENCES users(id) ON DELETE CASCADE, title VARCHAR(255) NOT NULL, description TEXT, status VARCHAR(50) DEFAULT 'PENDING', created_at TIMESTAMP DEFAULT NOW());"
                    }
                ],
                "indexes": ["CREATE INDEX idx_tasks_user_id ON tasks(user_id);"]
            })

        # 4. Critic Agent Prompt
        elif "critic" in prompt.lower() or "challenge" in prompt.lower():
            return json.dumps({
                "approved": True,
                "criticisms": ["Schema and requirements align. No critical flaws found."],
                "suggestions": ["Ensure task status has strict enum check."]
            })

        # 5. Developer Coding Agent Prompt
        elif "write code" in prompt.lower() or "developer" in prompt.lower() or "implement" in prompt.lower():
            self.developer_attempts += 1
            # First attempt: Write app code with an intentional bug (e.g. syntax error or import error in tasks endpoint)
            # This enables demonstrating the debugging / self-recovery loop
            if self.developer_attempts == 1:
                return json.dumps({
                    "files_to_create": [
                        {
                            "path": "app/models/user.py",
                            "content": "from sqlalchemy import Column, String, DateTime\nfrom sqlalchemy.dialects.postgresql import UUID\nimport uuid\nfrom app.core.database import Base\nclass User(Base):\n    __tablename__ = 'users'\n    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)\n    email = Column(String, unique=True, nullable=False)\n    hashed_password = Column(String, nullable=False)\n"
                        },
                        {
                            "path": "app/models/task.py",
                            "content": "from sqlalchemy import Column, String, ForeignKey, Text\nfrom sqlalchemy.dialects.postgresql import UUID\nimport uuid\nfrom app.core.database import Base\nclass Task(Base):\n    __tablename__ = 'tasks'\n    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)\n    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'))\n    title = Column(String, nullable=False)\n    description = Column(Text, nullable=True)\n    status = Column(String, default='PENDING')\n"
                        },
                        {
                            "path": "app/api/tasks.py",
                            "content": "from fastapi import APIRouter, Depends, HTTPException\nfrom app.models.task import Task\n# INTENTIONAL BUG: Missing import of get_db\nrouter = APIRouter(prefix='/tasks', tags=['tasks'])\n@router.get('')\ndef list_tasks(db = Depends(get_db_session_not_defined)): # Buggy function signature\n    return []\n"
                        }
                    ],
                    "message": "Generated basic FastAPI templates. Note: auth is placeholder."
                })
            else:
                # Second attempt (after debugging): return corrected code
                return json.dumps({
                    "files_to_create": [
                        {
                            "path": "app/api/tasks.py",
                            "content": "from fastapi import APIRouter, Depends\nfrom sqlalchemy.orm import Session\nfrom app.core.database import get_db\nrouter = APIRouter(prefix='/tasks', tags=['tasks'])\n@router.get('')\ndef list_tasks(db: Session = Depends(get_db)):\n    return []\n"
                        }
                    ],
                    "message": "Fixed the unresolved import and function parameters in tasks endpoint."
                })

        # 6. Testing Agent Prompt
        elif "test" in prompt.lower() or "pytest" in prompt.lower():
            if self.developer_attempts <= 1:
                return json.dumps({
                    "total": 5,
                    "passed": 4,
                    "failed": 1,
                    "coverage": 80.0,
                    "failures": [
                        {
                            "test_name": "test_list_tasks",
                            "error": "NameError: name 'get_db_session_not_defined' is not defined"
                        }
                    ]
                })
            else:
                return json.dumps({
                    "total": 5,
                    "passed": 5,
                    "failed": 0,
                    "coverage": 95.0,
                    "failures": []
                })

        # 7. Code Review Agent Prompt
        elif "review" in prompt.lower() or "code review" in prompt.lower():
            return json.dumps({
                "status": "PASS",
                "severity": "LOW",
                "issues": [
                    {"severity": "LOW", "description": "Missing docstrings in app/api/tasks.py API router."}
                ],
                "recommendations": [
                    "Add docstring to API endpoints to document parameters."
                ]
            })

        # Generic fallback
        return "Simulated text completion response."

    def stream(self, prompt: str, system_prompt: str | None = None) -> Generator[str, None, None]:
        yield self.generate(prompt, system_prompt)


def get_llm_provider(provider_type: str | None = None) -> LLMProvider:
    """Retrieve LLMProvider instance based on configuration."""
    settings = get_settings()
    provider = (provider_type or settings.llm_provider).lower()

    if provider == "ollama":
        # Check settings for model; we can default to llama3
        model = getattr(settings, "llm_model", "llama3")
        return OllamaProvider(base_url="http://localhost:11434", model=model)
    elif provider == "bedrock":
        return BedrockProvider(region_name=settings.aws_region, model_id=settings.bedrock_model_id)
    elif provider == "simulator":
        return SimulatorProvider()
    else:
        logger.warning(f"Unknown LLM provider: {provider}. Falling back to simulator.")
        return SimulatorProvider()
