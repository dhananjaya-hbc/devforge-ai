# DevForge AI — "An Autonomous Multi-Agent Software Engineering Team"

DevForge AI is an autonomous multi-agent software engineering platform that takes a high-level, natural-language software requirement and autonomously executes the complete software development lifecycle: requirements analysis, architectural design, database design, source code generation, automated test writing, sandboxed execution, failure diagnostics, self-repair loops, and comprehensive code reviews.

---

## 1. Product & Agent Architecture

DevForge AI implements a **closed-loop autonomous workflow**:
`OBSERVE` ➔ `PLAN` ➔ `ACT` ➔ `OBSERVE RESULT` ➔ `EVALUATE` ➔ `REFLECT` ➔ `REPLAN` ➔ `ACT AGAIN`

Rather than a simple linear pipeline, the system builds a **Dynamic Task Graph** where tasks have explicit dependencies and statuses (PENDING, READY, RUNNING, BLOCKED, FAILED, RETRYING, COMPLETED, CANCELLED).

### The Specialized Agents
- **Project Manager Agent**: Decomposes the high-level requirement into a graph of interdependent execution tasks and tracks progress.
- **Requirements Agent**: Extracts functional and non-functional specifications, constraints, and acceptance criteria into structured JSON.
- **Architect Agent**: Designs layer architectures, identifies modules, and establishes design patterns.
- **Database Agent**: Generates entity relations, indexes, and PostgreSQL schema definitions.
- **Developer Agent**: Writes the API endpoints, models, routers, and configurations.
- **Testing Agent**: Writes unit/integration tests and executes them inside an isolated Docker sandbox.
- **Code Review Agent**: Audits code quality, style, security vulnerabilities, and validation concerns.
- **Critic Agent**: Reviews intermediate decisions made by other agents and challenges weak design choices.

---

## 2. Technology Stack

- **Backend Framework**: FastAPI (Python 3.12/3.13)
- **Database**: PostgreSQL (SQLAlchemy ORM + Alembic Migrations)
- **Frontend Dashboard**: React SPA (Vite + Vanilla CSS)
- **Sandboxed Execution**: Isolated Docker containerization (`python:3.12-slim`)
- **LLM Abstraction Layer**: Open-weight models only — **Qwen 3.6** served by Groq, or fully local **Ollama** runtimes. A Simulator/Mock provider is included strictly for offline tests.

### Why the AI layer is open-source

The competition requires open-source models as the core intelligence, so DevForge
runs on **published open-weight models** (Qwen, Llama) and never on a proprietary
API such as GPT, Claude, or Gemini. Groq is inference hosting — rented GPUs
serving open weights — and can be swapped for local Ollama with one env var,
since every agent depends on the `LLMProvider` interface rather than any vendor.

---

## 3. Local Setup & Quick Start

Follow these steps to set up and run the complete application on your local machine:

### Step A: Start the Infrastructure via Docker Compose
Start the Postgres database in the background:
```bash
docker compose up -d
```
*Note: The Postgres container is mapped to port `5433` on the host to avoid port conflicts with native database instances, and maps to `5432` internally for Docker network communication.*

### Step B: Create Local Environment file (`.env`)
Create a `.env` file in the root directory. You can copy the template:
```bash
cp .env.example .env
```
Inside `.env`, verify or set:
```env
# --- App ---
ENVIRONMENT=development

# --- Database ---
POSTGRES_USER=devforge
POSTGRES_PASSWORD=devforge
POSTGRES_DB=devforge
DATABASE_URL=postgresql+psycopg://devforge:devforge@localhost:5433/devforge

# --- LLM (open-weight models only) ---
LLM_PROVIDER=groq
LLM_MODEL=qwen/qwen3.6-27b
GROQ_API_KEY=your_key_here
```

Get a free Groq key at [console.groq.com/keys](https://console.groq.com/keys).

**Alternatives:**
- **Fully local, no key** — install [Ollama](https://ollama.com), `ollama pull llama3.1`, then set
  `LLM_PROVIDER=ollama` and `LLM_MODEL=llama3.1`.
- **`LLM_PROVIDER=simulator`** returns canned fixtures for offline testing. It performs
  no inference, so never use it for a demo or for any reported metric.

> **Note on Groq's free tier:** the limit is 8,000 tokens/minute, and each agent call
> spends roughly 4,000 (Qwen is a reasoning model). A full project run therefore
> pauses for rate limits; the provider backs off and retries automatically.

### Step C: Setup Local Virtual Environment & Apply DB Migrations
Generate a virtual environment on the host to run database migrations, CLI commands, and test suites:
```bash
# Create and activate python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install requirements
pip install -r backend/requirements.txt

# Apply migrations
export DATABASE_URL="postgresql+psycopg://devforge:devforge@localhost:5433/devforge"
cd backend
alembic upgrade head
cd ..
```

### Step D: Run Backend Development Server
Run the FastAPI backend on host port `8000`:
```bash
source .venv/bin/activate
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```
*The backend API Docs will be available at `http://localhost:8000/docs`.*

### Step E: Run Frontend React Dashboard
In a separate terminal, install the frontend packages and launch the Vite development server:
```bash
cd frontend
npm install
npm run dev
```
*The dashboard will be active at `http://localhost:5173`.*

---

## 4. Running the Demo Scenario

1. Open the React Dashboard at `http://localhost:5173`.
2. Under **Create New Project** in the sidebar, input:
   - **Project Name**: `Task Manager REST API`
   - **Goal / Requirements**: `Build a task management REST API with authentication. Users can register, log in, create tasks, update tasks, delete tasks, and mark tasks as completed.`
3. Click **START PROJECT**.
4. Once the project card appears in the sidebar list, click **START RUN**.
5. Navigate through the tabs:
   - **Task Graph**: View real-time status transitions.
   - **Live Activity Feed**: Watch log streams emitted directly by PM, Requirements, Architect, Developer, Testing, and Code Review agents.
   - **Generated Workspace Files**: Browse the written FastAPI routers, models, schemas, and test suites.
   - **Test Results**: See the pytest runs, logs, and coverage.
     - *Notice how the first Developer write introduces an intentional import syntax bug, the Testing Agent executes and fails, and the Developer Agent autonomously diagnoses, corrects, and restarts the test loop successfully!*
   - **Code Review**: View final severity audits, issues checklist, and recommendations.

---

## 5. Production VPS Deployment Configuration

For deploying to a production VPS (DigitalOcean, Hetzner, Linode, etc.):
1. **Container Registry**: Build and push your Backend and Frontend images to any standard container registry (e.g., Docker Hub, GitHub Packages).
2. **Database**: Set up a managed Postgres instance (e.g., Railway, Render, or a self-hosted Docker volume on your VPS).
3. **Application Server**: Run the services using Docker Compose on any Linux VM.
4. **Proxy & SSL**: Configure Nginx or Caddy as a reverse proxy to route public traffic and handle automatic SSL certificates (via Let's Encrypt).
