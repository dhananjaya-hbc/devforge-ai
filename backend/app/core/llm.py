import abc
import json
import logging
import re
from collections.abc import Generator
from typing import Any, Type

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





class SimulatorProvider(LLMProvider):
    """Simulator provider pre-programmed with high-fidelity responses for DevForge AI demo goals."""
    
    def __init__(self):
        # Keeps track of developer coding attempts to simulate a code bug -> fail -> fix loop
        self.developer_attempts = 0

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        sys = (system_prompt or "").lower()
        p_lower = prompt.lower()
        
        # Check if the prompt relates to frontend, react, css, html or dashboard
        is_frontend = any(x in p_lower or x in sys for x in ["react", "frontend", "dashboard", "css", "html", "ui"])

        # 1. PM/Requirements Extraction Prompt
        if "business analyst" in sys or "requirements" in sys or ("ambiguities" in p_lower and "functional_requirements" in p_lower):
            if is_frontend:
                return json.dumps({
                    "functional_requirements": [
                        {"id": "FR-1", "description": "Display sales metrics cards (Revenue, Orders, Conversion)"},
                        {"id": "FR-2", "description": "Interactive chart displaying monthly sales trends"},
                        {"id": "FR-3", "description": "Recent orders table with status badges (Completed, Pending, Cancelled)"},
                        {"id": "FR-4", "description": "Active inventory stock level list with alert triggers"}
                    ],
                    "non_functional_requirements": [
                        {"id": "NFR-1", "description": "Responsive layout supporting desktop and mobile dimensions"},
                        {"id": "NFR-2", "description": "Premium glassmorphic styling utilizing vanilla CSS variables"}
                    ],
                    "constraints": [
                        {"id": "CON-1", "description": "Must be built as a single-page React component"},
                        {"id": "CON-2", "description": "No external heavy chart libraries allowed, build simple native SVG charts"}
                    ],
                    "ambiguities": [],
                    "acceptance_criteria": [
                        {"id": "AC-1", "description": "Metrics cards highlight positive/negative changes"},
                        {"id": "AC-2", "description": "Stock count below 5 units displays a warning alert badge"}
                    ]
                })
            else:
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
        elif "software architect" in sys or "architect" in sys:
            if is_frontend:
                return json.dumps({
                    "modules": [
                        {"name": "src/App.jsx", "description": "Main layout containing dashboard grid and state management"},
                        {"name": "src/components/Metrics.jsx", "description": "Renders summary cards for key ecommerce variables"},
                        {"name": "src/components/OrdersTable.jsx", "description": "Renders paginated transaction records"},
                        {"name": "src/components/Inventory.jsx", "description": "Displays active stock status list"},
                        {"name": "src/styles/dashboard.css", "description": "Vanilla CSS file containing variables, glassmorphic styles, and layouts"}
                    ],
                    "design_patterns": ["State-lifting parent controller pattern", "Sub-component modular decomposition"],
                    "security_spec": "XSS sanitization on user input renders"
                })
            else:
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
        elif "database engineer" in sys or "database" in sys:
            if is_frontend:
                return json.dumps({
                    "tables": [
                        {
                            "name": "LocalState_Orders",
                            "sql": "React state schema representing recent orders dataset."
                        },
                        {
                            "name": "LocalState_Inventory",
                            "sql": "React state schema tracking product stock counts."
                        }
                    ],
                    "indexes": ["React state memoization keys index by order UUID."]
                })
            else:
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
        elif "agent critic" in sys or "critic" in sys:
            if is_frontend:
                return json.dumps({
                    "approved": True,
                    "criticisms": ["Layout structure and component definitions are modular. Style guides align."],
                    "suggestions": ["Ensure responsiveness for mobile layouts is fully verified."]
                })
            else:
                return json.dumps({
                    "approved": True,
                    "criticisms": ["Schema and requirements align. No critical flaws found."],
                    "suggestions": ["Ensure task status has strict enum check."]
                })

        # 5. Developer Coding Agent Prompt
        elif "backend engineer" in sys or "backend" in sys or "developer" in sys:
            self.developer_attempts += 1
            if is_frontend:
                # First attempt: Write app code with an intentional typo bug in React import to demonstrate self-healing
                if self.developer_attempts == 1:
                    return json.dumps({
                        "files_to_create": [
                            {
                                "path": "src/styles/dashboard.css",
                                "content": ":root {\n  --bg-gradient: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);\n  --glass-bg: rgba(255, 255, 255, 0.03);\n  --glass-border: rgba(255, 255, 255, 0.08);\n  --text-primary: #f8fafc;\n  --text-secondary: #94a3b8;\n}\n.dashboard-container {\n  min-height: 100vh;\n  background: var(--bg-gradient);\n  color: var(--text-primary);\n  padding: 2rem;\n}\n.metric-card {\n  background: var(--glass-bg);\n  border: 1px solid var(--glass-border);\n  border-radius: 12px;\n  padding: 1.5rem;\n  transition: all 0.3s ease;\n}\n.metric-card:hover {\n  transform: translateY(-2px);\n  border-color: rgba(255,255,255,0.2);\n}\n"
                            },
                            {
                                "path": "src/components/Metrics.jsx",
                                "content": "import React from 'react';\nexport function Metrics() {\n  const data = [\n    { title: 'Total Revenue', value: '$24,580', change: '+12.5%', isUp: true },\n    { title: 'Active Orders', value: '382', change: '+8.3%', isUp: true },\n    { title: 'Conversion Rate', value: '3.2%', change: '-0.4%', isUp: false }\n  ];\n  return (\n    <div style={{ display: 'flex', gap: '1rem', width: '100%' }}>\n      {data.map((m, i) => (\n        <div key={i} className='metric-card' style={{ flex: 1 }}>\n          <h3 style={{ color: '#94a3b8', fontSize: '0.875rem' }}>{m.title}</h3>\n          <p style={{ fontSize: '1.8rem', fontWeight: 'bold', margin: '0.5rem 0' }}>{m.value}</p>\n          <span style={{ color: m.isUp ? '#10b981' : '#ef4444', fontSize: '0.875rem' }}>{m.change}</span>\n        </div>\n      ))}\n    </div>\n  );\n}\n"
                            },
                            {
                                "path": "src/App.jsx",
                                "content": "import React from 'react';\nimport { MetricsCard } from './components/Metrics'; // INTENTIONAL TYPO BUG\nexport default function App() {\n  return (\n    <div className='dashboard-container'>\n      <h1 style={{ marginBottom: '1.5rem' }}>E-Commerce Store Dashboard</h1>\n      <MetricsCard />\n    </div>\n  );\n}\n"
                            }
                        ],
                        "message": "Generated e-commerce dashboard template files. App.jsx contains metrics component."
                    })
                else:
                    # Second attempt (after debugging): return corrected React code
                    return json.dumps({
                        "files_to_create": [
                            {
                                "path": "src/App.jsx",
                                "content": "import React from 'react';\nimport { Metrics } from './components/Metrics'; // FIXED TYPO BUG\nexport default function App() {\n  return (\n    <div className='dashboard-container'>\n      <h1 style={{ marginBottom: '1.5rem', fontSize: '2rem' }}>E-Commerce Store Dashboard</h1>\n      <Metrics />\n      <div style={{ marginTop: '2rem', padding: '1.5rem', background: 'rgba(255,255,255,0.02)', borderRadius: '12px' }}>\n        <h2>Recent Orders</h2>\n        <p style={{ color: '#94a3b8' }}>Client orders logs are currently empty.</p>\n      </div>\n    </div>\n  );\n}\n"
                            }
                        ],
                        "message": "Fixed the unresolved import in App.jsx."
                    })
            else:
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
        elif "qa automation" in sys or "qa" in sys or "test" in p_lower or "pytest" in p_lower:
            if is_frontend:
                if self.developer_attempts <= 1:
                    return json.dumps({
                        "total": 3,
                        "passed": 2,
                        "failed": 1,
                        "coverage": 75.0,
                        "failures": [
                            {
                                "test_name": "App Component Mounts",
                                "error": "ModuleNotFoundError: Cannot find module './components/Metrics' in src/App.jsx"
                            }
                        ]
                    })
                else:
                    return json.dumps({
                        "total": 3,
                        "passed": 3,
                        "failed": 0,
                        "coverage": 90.0,
                        "failures": []
                    })
            else:
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
        elif "code reviewer" in sys or "reviewer" in sys or "review" in p_lower:
            if is_frontend:
                return json.dumps({
                    "status": "PASS",
                    "severity": "LOW",
                    "issues": [
                        {"severity": "LOW", "description": "Add alt/aria tags to SVG indicators for web accessibility."}
                    ],
                    "recommendations": [
                        "Include accessibility properties to metrics grid values."
                    ]
                })
            else:
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


class GroqProvider(LLMProvider):
    """Groq-hosted open-weight models (Llama family) via the OpenAI-compatible API.

    Groq only serves models with published weights, which keeps the AI layer
    open-source even though the inference is remote.
    """

    BASE_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key
        self.model = model

    def _build_payload(self, prompt: str, system_prompt: str | None, stream: bool) -> dict:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "stream": stream,
        }
        # generate_structured() appends a JSON schema; Groq's JSON mode then
        # guarantees syntactically valid JSON instead of relying on the prompt.
        if "json schema:" in prompt.lower():
            payload["response_format"] = {"type": "json_object"}
        return payload

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        payload = self._build_payload(prompt, system_prompt, stream=False)
        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.post(self.BASE_URL, json=payload, headers=self._headers)
                response.raise_for_status()
                choices = response.json().get("choices", [])
                if not choices:
                    raise RuntimeError("Groq API returned no choices.")
                return choices[0].get("message", {}).get("content", "")
        except httpx.HTTPStatusError as e:
            logger.error(f"Groq HTTP {e.response.status_code}: {e.response.text}")
            raise RuntimeError(f"Groq request failed ({e.response.status_code}): {e.response.text}")
        except Exception as e:
            logger.error(f"Groq generate error: {e}")
            raise RuntimeError(f"Groq invocation failed: {e}")

    def stream(self, prompt: str, system_prompt: str | None = None) -> Generator[str, None, None]:
        payload = self._build_payload(prompt, system_prompt, stream=True)
        try:
            with httpx.Client(timeout=120.0) as client:
                with client.stream("POST", self.BASE_URL, json=payload, headers=self._headers) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            break
                        chunk = json.loads(data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        if content := delta.get("content"):
                            yield content
        except Exception as e:
            logger.error(f"Groq stream error: {e}")
            raise RuntimeError(f"Groq streaming failed: {e}")


def get_llm_provider(provider_type: str | None = None) -> LLMProvider:
    """Retrieve LLMProvider instance based on configuration.

    Misconfiguration raises rather than silently degrading to the simulator,
    so a demo can never appear to run on a real model when it is not.
    """
    settings = get_settings()
    provider = (provider_type or settings.llm_provider).lower()

    if provider == "groq":
        if not settings.groq_api_key:
            raise RuntimeError(
                "LLM_PROVIDER=groq but GROQ_API_KEY is not set. "
                "Get a free key at https://console.groq.com/keys"
            )
        return GroqProvider(api_key=settings.groq_api_key, model=settings.llm_model)
    elif provider == "ollama":
        return OllamaProvider(base_url=settings.ollama_base_url, model=settings.llm_model)
    elif provider == "simulator":
        logger.warning(
            "Using SimulatorProvider: responses are canned fixtures, not model output. "
            "Never use this for a demo or for reported metrics."
        )
        return SimulatorProvider()
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider!r}. Supported: groq, ollama, simulator."
        )
