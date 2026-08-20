import React, { useState, useEffect, useRef, useCallback } from 'react';

const API_BASE = 'http://localhost:8000/api';

const EXAMPLE_GOALS = [
  { label: 'Task API', goal: 'Build a task management REST API with authentication.' },
  { label: 'URL shortener', goal: 'Build a URL shortener API with click analytics.' },
  { label: 'Blog API', goal: 'Build a blog API with posts, comments, and tags.' },
];

const TABS = [
  { id: 'graph', label: 'Tasks' },
  { id: 'logs', label: 'Activity' },
  { id: 'files', label: 'Files' },
  { id: 'tests', label: 'Tests' },
  { id: 'reviews', label: 'Review' },
];

const AGENT_CLASSES = {
  projectmanager: 'pm',
  requirements: 'req',
  architect: 'arch',
  database: 'db',
  developer: 'dev',
  testing: 'test',
  codereview: 'review',
  critic: 'critic',
};

function agentClass(name) {
  if (!name) return '';
  const key = Object.keys(AGENT_CLASSES).find((k) => name.toLowerCase().includes(k));
  return key ? AGENT_CLASSES[key] : '';
}

/** "DeveloperAgent" -> "Developer" */
function agentLabel(name) {
  if (!name) return 'System';
  return name.replace(/Agent$/, '').replace(/([a-z])([A-Z])/g, '$1 $2');
}

function timeOnly(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function Icon({ name, size = 16 }) {
  const paths = {
    file: 'M4 2h6l4 4v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z',
    folder: 'M2 4a1 1 0 0 1 1-1h3l2 2h5a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V4z',
    inbox: 'M2 10h4l1 2h2l1-2h4M3 3h10l1 7v3a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1v-3l1-7z',
    check: 'M3 8.5l3.5 3.5L13 5',
    refresh: 'M13 8a5 5 0 1 1-1.5-3.5M13 2v3h-3',
  };
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}

function StatusPill({ status }) {
  if (!status) return null;
  const key = String(status).toLowerCase();
  return (
    <span className={`pill ${key}`}>
      <span className="pill-dot" />
      {status}
    </span>
  );
}

function EmptyState({ icon = 'inbox', title, text }) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon name={icon} size={20} />
      </div>
      <div className="empty-title">{title}</div>
      {text && <p className="empty-text">{text}</p>}
    </div>
  );
}

function App() {
  const [projects, setProjects] = useState([]);
  const [activeProjectId, setActiveProjectId] = useState(null);
  const [projectData, setProjectData] = useState(null);
  const [tasks, setTasks] = useState([]);
  const [events, setEvents] = useState([]);
  const [files, setFiles] = useState([]);
  const [activeFileId, setActiveFileId] = useState(null);
  const [fileContent, setFileContent] = useState(null);
  const [testRuns, setTestRuns] = useState([]);
  const [reviews, setReviews] = useState([]);

  const [activeTab, setActiveTab] = useState('graph');
  const [newGoal, setNewGoal] = useState('');
  const [newName, setNewName] = useState('');
  const [loading, setLoading] = useState(false);
  const [connected, setConnected] = useState(false);
  const [copied, setCopied] = useState(false);

  const feedEndRef = useRef(null);
  const eventSourceRef = useRef(null);

  const fetchProjects = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/projects`);
      if (!res.ok) return;
      const data = await res.json();
      setProjects(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error('Error fetching projects:', err);
    }
  }, []);

  const fetchFileContent = useCallback(async (projectId, fileId) => {
    try {
      const res = await fetch(`${API_BASE}/projects/${projectId}/files/${fileId}/content`);
      if (!res.ok) return;
      setActiveFileId(fileId);
      setFileContent(await res.json());
    } catch (err) {
      console.error('Error reading file:', err);
    }
  }, []);

  const fetchActiveProjectDetails = useCallback(
    async (projectId) => {
      if (!projectId) return;

      const load = async (path, setter) => {
        try {
          const res = await fetch(`${API_BASE}/projects/${projectId}${path}`);
          if (res.ok) setter(await res.json());
        } catch (err) {
          console.error(`Error loading ${path}:`, err);
        }
      };

      await Promise.all([
        load('', setProjectData),
        load('/tasks', setTasks),
        load('/tests', setTestRuns),
        load('/reviews', setReviews),
        load('/files', (data) => {
          setFiles(data);
          if (data.length > 0 && !activeFileId) fetchFileContent(projectId, data[0].id);
        }),
      ]);
    },
    [activeFileId, fetchFileContent]
  );

  const handleCreateProject = async (e) => {
    e.preventDefault();
    if (!newGoal.trim()) return;

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/projects`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal: newGoal, name: newName || null }),
      });
      if (res.ok) {
        const data = await res.json();
        setNewGoal('');
        setNewName('');
        setProjects((prev) => [data, ...prev]);
        selectProject(data.id);
      }
    } catch (err) {
      console.error('Error creating project:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleControlAction = async (action) => {
    if (!activeProjectId) return;
    try {
      const res = await fetch(`${API_BASE}/projects/${activeProjectId}/${action}`, {
        method: 'POST',
      });
      if (res.ok) fetchActiveProjectDetails(activeProjectId);
    } catch (err) {
      console.error(`Error triggering ${action}:`, err);
    }
  };

  const selectProject = (id) => {
    setActiveProjectId(id);
    setFileContent(null);
    setActiveFileId(null);
  };

  const copyCode = async () => {
    if (!fileContent?.content) return;
    await navigator.clipboard.writeText(fileContent.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };

  // Live telemetry stream
  useEffect(() => {
    if (!activeProjectId) return;

    setEvents([]);
    eventSourceRef.current?.close();

    const es = new EventSource(`${API_BASE}/projects/${activeProjectId}/events/stream`);
    eventSourceRef.current = es;

    es.onopen = () => setConnected(true);

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setEvents((prev) => (prev.some((e) => e.id === data.id) ? prev : [...prev, data]));

        const t = data.event_type || '';
        if (t.includes('COMPLETED') || t.includes('FAILED') || t.includes('CREATED')) {
          fetchActiveProjectDetails(activeProjectId);
        }
      } catch (err) {
        console.error('Error parsing SSE event:', err);
      }
    };

    es.onerror = () => setConnected(false);

    return () => {
      es.close();
      setConnected(false);
    };
  }, [activeProjectId]);

  // Polling fallback for data not carried by the event stream
  useEffect(() => {
    if (!activeProjectId) return;
    fetchActiveProjectDetails(activeProjectId);
    const interval = setInterval(() => fetchActiveProjectDetails(activeProjectId), 4000);
    return () => clearInterval(interval);
  }, [activeProjectId]);

  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events]);

  useEffect(() => {
    fetchProjects();
    const interval = setInterval(fetchProjects, 10000);
    return () => clearInterval(interval);
  }, [fetchProjects]);

  useEffect(() => {
    if (projects.length > 0 && !activeProjectId) setActiveProjectId(projects[0].id);
  }, [projects, activeProjectId]);

  const activeProject = projects.find((p) => p.id === activeProjectId) || projectData;
  const doneCount = tasks.filter((t) => t.status === 'COMPLETED').length;
  const progress = tasks.length ? Math.round((doneCount / tasks.length) * 100) : 0;
  const latestTest = testRuns[0];
  const latestReview = reviews[0];

  const tabCounts = {
    graph: tasks.length,
    logs: events.length,
    files: files.length,
    tests: testRuns.length,
    reviews: reviews.length,
  };

  return (
    <div className="app">
      <nav className="nav">
        <div className="nav-brand">
          <span className="nav-mark">DF</span>
          DevForge AI
        </div>
        <div className="nav-meta">
          <span className="live">
            <span className={`live-dot ${connected ? 'on' : 'off'}`} />
            {connected ? 'Live' : 'Offline'}
          </span>
          <button className="btn btn-ghost btn-sm" onClick={fetchProjects}>
            <Icon name="refresh" size={13} />
            Refresh
          </button>
        </div>
      </nav>

      <div className="layout">
        <aside className="sidebar">
          <form onSubmit={handleCreateProject} className="stack">
            <div className="section-label">New project</div>

            <div className="field">
              <label htmlFor="goal">What should the team build?</label>
              <textarea
                id="goal"
                className="textarea"
                placeholder="Build a REST API for a task management app with user accounts…"
                value={newGoal}
                onChange={(e) => setNewGoal(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleCreateProject(e);
                }}
                required
              />
              <span className="field-hint">Describe the goal in plain language. ⌘↵ to submit.</span>
            </div>

            <div className="examples">
              <span className="examples-label">Try</span>
              {EXAMPLE_GOALS.map(({ label, goal }, i) => (
                <React.Fragment key={label}>
                  {i > 0 && <span className="examples-sep">·</span>}
                  <button type="button" className="example-link" onClick={() => setNewGoal(goal)}>
                    {label}
                  </button>
                </React.Fragment>
              ))}
            </div>

            <div className="field">
              <label htmlFor="name">Name (optional)</label>
              <input
                id="name"
                type="text"
                className="input"
                placeholder="Task API"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
              />
            </div>

            <button type="submit" className="btn btn-primary btn-block" disabled={loading || !newGoal.trim()}>
              {loading ? 'Creating…' : 'Create project'}
            </button>
          </form>

          <div className="stack">
            <div className="section-label">Projects</div>
            {projects.length === 0 ? (
              <p className="field-hint">Nothing yet — create your first project above.</p>
            ) : (
              <div className="project-list">
                {projects.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    className={`project-item ${p.id === activeProjectId ? 'active' : ''}`}
                    onClick={() => selectProject(p.id)}
                  >
                    <div className="project-item-top">
                      <span className="project-item-name">{p.name}</span>
                      <StatusPill status={p.status} />
                    </div>
                    <p className="project-item-goal truncate-2">{p.goal}</p>
                  </button>
                ))}
              </div>
            )}
          </div>
        </aside>

        <main className="main">
          {!activeProject ? (
            <div className="welcome">
              <h1>An autonomous software engineering team</h1>
              <p>
                Describe what you want built. Eight agents plan it, design it, write it, test it in a
                sandbox, and review it — then show you their work.
              </p>
              <div className="welcome-steps">
                <div className="welcome-step">
                  <span className="welcome-step-num">1</span>
                  <p className="muted">Describe your goal in plain language</p>
                </div>
                <div className="welcome-step">
                  <span className="welcome-step-num">2</span>
                  <p className="muted">Watch the agents plan and build it</p>
                </div>
                <div className="welcome-step">
                  <span className="welcome-step-num">3</span>
                  <p className="muted">Review the generated code and tests</p>
                </div>
              </div>
            </div>
          ) : (
            <>
              <header className="project-header">
                <div>
                  <h1 className="project-title">{activeProject.name}</h1>
                  <p className="project-goal">{activeProject.goal}</p>
                </div>

                <div className="stack">
                  <div className="row" style={{ justifyContent: 'flex-end' }}>
                    <StatusPill status={activeProject.status} />
                  </div>
                  <div className="header-actions">
                    {activeProject.status === 'CREATED' && (
                      <button className="btn btn-primary" onClick={() => handleControlAction('start')}>
                        Start run
                      </button>
                    )}
                    {activeProject.status === 'RUNNING' && (
                      <button className="btn btn-secondary" onClick={() => handleControlAction('pause')}>
                        Pause
                      </button>
                    )}
                    {activeProject.status === 'PAUSED' && (
                      <button className="btn btn-primary" onClick={() => handleControlAction('resume')}>
                        Resume
                      </button>
                    )}
                    {['RUNNING', 'PAUSED', 'CREATED'].includes(activeProject.status) && (
                      <button className="btn btn-danger" onClick={() => handleControlAction('cancel')}>
                        Cancel
                      </button>
                    )}
                  </div>
                </div>
              </header>

              {tasks.length > 0 && (
                <div className="progress">
                  <div className="progress-track">
                    <div
                      className={`progress-fill ${progress === 100 ? 'complete' : ''}`}
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                  <span className="progress-label">
                    {doneCount} of {tasks.length} tasks complete
                  </span>
                </div>
              )}

              <div className="tabs">
                {TABS.map((tab) => (
                  <button
                    key={tab.id}
                    className={`tab ${activeTab === tab.id ? 'active' : ''}`}
                    onClick={() => setActiveTab(tab.id)}
                  >
                    {tab.label}
                    {tabCounts[tab.id] > 0 && <span className="tab-count">{tabCounts[tab.id]}</span>}
                  </button>
                ))}
              </div>

              <section className="fade-in">
                {activeTab === 'graph' &&
                  (tasks.length === 0 ? (
                    <EmptyState
                      title="No tasks yet"
                      text="Press Start run and the Project Manager agent will break your goal into a dependency graph."
                    />
                  ) : (
                    <div className="task-grid">
                      {tasks.map((t, i) => (
                        <article key={t.id} className={`task-card ${t.status.toLowerCase()}`}>
                          <div className="row-between">
                            <span className="task-step">STEP {i + 1}</span>
                            <StatusPill status={t.status} />
                          </div>
                          <h3 className="task-title">{t.title}</h3>
                          <div className="task-meta">
                            <span className="task-agent">
                              <span className={`agent-dot ${agentClass(t.assigned_agent)}`} />
                              {agentLabel(t.assigned_agent)}
                            </span>
                            {t.attempts > 1 && <span className="attempts">Attempt {t.attempts}/3</span>}
                          </div>
                        </article>
                      ))}
                    </div>
                  ))}

                {activeTab === 'logs' &&
                  (events.length === 0 ? (
                    <EmptyState
                      title="Waiting for activity"
                      text="Agent events appear here in real time as the run progresses."
                    />
                  ) : (
                    <div className="feed card-sunken" style={{ padding: '4px 14px' }}>
                      {events.map((e, idx) => (
                        <div key={e.id || idx} className="feed-row">
                          <span className="feed-time">{timeOnly(e.created_at)}</span>
                          <div>
                            <div className="feed-head">
                              <span className={`agent-dot ${agentClass(e.agent)}`} />
                              <span className="feed-agent">{agentLabel(e.agent)}</span>
                              <span className="feed-type">{e.event_type}</span>
                            </div>
                            <div className="feed-message">{e.message}</div>
                            {e.payload && (
                              <details className="feed-payload">
                                <summary>Show details</summary>
                                <pre>{JSON.stringify(e.payload, null, 2)}</pre>
                              </details>
                            )}
                          </div>
                        </div>
                      ))}
                      <div ref={feedEndRef} />
                    </div>
                  ))}

                {activeTab === 'files' &&
                  (files.length === 0 ? (
                    <EmptyState
                      icon="folder"
                      title="No files generated yet"
                      text="Files written by the Developer agent into the sandbox will appear here."
                    />
                  ) : (
                    <div className="files">
                      <div className="file-list">
                        {files.map((f) => (
                          <button
                            key={f.id}
                            className={`file-item ${f.id === activeFileId ? 'active' : ''}`}
                            onClick={() => fetchFileContent(activeProjectId, f.id)}
                            title={f.path}
                          >
                            <span className="file-icon">
                              <Icon name="file" size={13} />
                            </span>
                            <span className="file-name">{f.path}</span>
                          </button>
                        ))}
                      </div>

                      <div className="code-pane">
                        {fileContent ? (
                          <>
                            <div className="code-head">
                              <span>{fileContent.path}</span>
                              <button className="btn btn-ghost btn-sm" onClick={copyCode}>
                                {copied ? 'Copied' : 'Copy'}
                              </button>
                            </div>
                            <pre className="code-body">
                              <code>{fileContent.content}</code>
                            </pre>
                          </>
                        ) : (
                          <EmptyState icon="file" title="Select a file" text="Choose a file to view its source." />
                        )}
                      </div>
                    </div>
                  ))}

                {activeTab === 'tests' &&
                  (!latestTest ? (
                    <EmptyState
                      title="No test runs yet"
                      text="The Testing agent runs pytest inside an isolated Docker sandbox and reports the real result here."
                    />
                  ) : (
                    <>
                      <div className="metrics">
                        <div className="metric">
                          <div className="metric-label">Total</div>
                          <div className="metric-value">{latestTest.total}</div>
                        </div>
                        <div className="metric">
                          <div className="metric-label">Passed</div>
                          <div className={`metric-value ${latestTest.passed > 0 ? 'good' : ''}`}>
                            {latestTest.passed}
                          </div>
                        </div>
                        <div className="metric">
                          <div className="metric-label">Failed</div>
                          <div className={`metric-value ${latestTest.failed > 0 ? 'bad' : ''}`}>
                            {latestTest.failed}
                          </div>
                        </div>
                        <div className="metric">
                          <div className="metric-label">Coverage</div>
                          <div className="metric-value">{latestTest.coverage}%</div>
                          {!latestTest.coverage && <div className="metric-sub">Not measured</div>}
                        </div>
                      </div>

                      {testRuns.length > 1 && (
                        <div className="notice notice-info" style={{ marginBottom: 16 }}>
                          <div>
                            <div className="notice-title">Recovery loop ran</div>
                            {testRuns.length} test runs recorded — the Developer agent revised the code and
                            tests were executed again.
                          </div>
                        </div>
                      )}

                      <div className="section-label" style={{ marginBottom: 8 }}>
                        Sandbox output
                      </div>
                      <pre className="code-body card-sunken">
                        {latestTest.stdout || 'No output captured from the sandbox.'}
                      </pre>
                    </>
                  ))}

                {activeTab === 'reviews' &&
                  (!latestReview ? (
                    <EmptyState
                      title="No review yet"
                      text="After tests run, the Code Review agent audits security, structure, and error handling."
                    />
                  ) : (
                    <>
                      <div className="metrics">
                        <div className="metric">
                          <div className="metric-label">Result</div>
                          <div
                            className={`metric-value ${latestReview.status === 'FAIL' ? 'bad' : 'good'}`}
                          >
                            {latestReview.status}
                          </div>
                        </div>
                        <div className="metric">
                          <div className="metric-label">Highest severity</div>
                          <div
                            className={`metric-value ${
                              ['HIGH', 'CRITICAL'].includes(latestReview.severity) ? 'bad' : ''
                            }`}
                          >
                            {latestReview.severity}
                          </div>
                        </div>
                        <div className="metric">
                          <div className="metric-label">Issues</div>
                          <div className="metric-value">{latestReview.issues?.length || 0}</div>
                        </div>
                      </div>

                      <div className="section-label" style={{ marginBottom: 8 }}>
                        Issues
                      </div>
                      <div className="card-sunken" style={{ padding: '4px 16px', marginBottom: 22 }}>
                        {latestReview.issues?.length ? (
                          <div className="issues">
                            {latestReview.issues.map((issue, idx) => (
                              <div key={idx} className="issue">
                                <span className={`pill ${String(issue.severity).toLowerCase()}`}>
                                  {issue.severity}
                                </span>
                                <span>{issue.description}</span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="muted" style={{ padding: '14px 0', fontSize: 13 }}>
                            No issues found.
                          </p>
                        )}
                      </div>

                      {latestReview.recommendations?.length > 0 && (
                        <>
                          <div className="section-label" style={{ marginBottom: 8 }}>
                            Recommendations
                          </div>
                          <div className="rec-list">
                            {latestReview.recommendations.map((rec, idx) => (
                              <div key={idx} className="rec-item">
                                <span className="rec-bullet">
                                  <Icon name="check" size={13} />
                                </span>
                                <span>{rec}</span>
                              </div>
                            ))}
                          </div>
                        </>
                      )}
                    </>
                  ))}
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
