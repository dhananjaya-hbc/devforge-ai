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
- **LLM Abstraction Layer**: Built-in support for local **Ollama** runtimes, **AWS Bedrock** (Llama 3.1 / Claude), and a high-fidelity **Simulator/Mock Provider** for local verification.

---

## 3. Local Setup & Quick Start

Follow these steps to set up and run the complete application on your local machine:

### Step A: Start the Infrastructure via Docker Compose
Start the Postgres database and local Ollama services in the background:
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

# --- LLM Provider Selection ---
# Set to 'simulator' to test out-of-the-box, or 'ollama' / 'bedrock'
LLM_PROVIDER=simulator
```

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

## 5. AWS Production Deployment Configuration

For deploying to AWS:
1. **Container Registry**: Push the Backend Docker image to **Amazon ECR**.
2. **Backend Engine**: Run the container in **AWS ECS Fargate** inside a private subnet.
3. **Database**: Provision an **Amazon RDS PostgreSQL** instance.
4. **Static Frontend**: Deploy the React Vite static build folder to **Amazon S3** distributed via **Amazon CloudFront**.
5. **Credentials Security**: Store AWS Bedrock connection keys and RDS database passwords in **AWS Secrets Manager**.
