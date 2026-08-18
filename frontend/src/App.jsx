import React, { useState, useEffect, useRef } from 'react';

const API_BASE = 'http://localhost:8000/api';

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
  
  // Tabs: 'graph' | 'logs' | 'files' | 'tests' | 'reviews'
  const [activeTab, setActiveTab] = useState('graph');
  
  // Form inputs
  const [newGoal, setNewGoal] = useState('');
  const [newName, setNewName] = useState('');
  const [loading, setLoading] = useState(false);

  const logsEndRef = useRef(null);
  const eventSourceRef = useRef(null);

  // 1. Fetch Projects list
  const fetchProjects = async () => {
    try {
      const res = await fetch(`${API_BASE}/projects`);
      if (res.ok) {
        const data = await res.json();
        // Since get /api/projects is not directly exposed as list in default route (we did not define list route yet),
        // Wait, did projects.py have a GET /api/projects list route?
        // Let's check: POST /api/projects (line 25), GET /api/projects/{id} (line 42)
        // Ah! There was NO GET /api/projects list endpoint in the original routes!
        // We will add a list endpoint to projects.py, but for App robustness let's verify.
        // Yes, we will implement list endpoint in projects.py if needed, or we can query active projects.
        // Let's create an endpoint in projects.py: @router.get("", response_model=list[ProjectRead]) to list all projects.
        // Let's fetch projects and fall back to empty if failure.
        const projectsData = Array.isArray(data) ? data : [];
        setProjects(projectsData);
      }
    } catch (err) {
      console.error('Error fetching projects:', err);
    }
  };

  // 2. Fetch Active Project details
  const fetchActiveProjectDetails = async (projectId) => {
    if (!projectId) return;
    try {
      // Get Project info
      const pRes = await fetch(`${API_BASE}/projects/${projectId}`);
      if (pRes.ok) {
        const data = await pRes.json();
        setProjectData(data);
      }

      // Get Tasks
      const tRes = await fetch(`${API_BASE}/projects/${projectId}/tasks`);
      if (tRes.ok) {
        const data = await tRes.json();
        setTasks(data);
      }

      // Get Files
      const fRes = await fetch(`${API_BASE}/projects/${projectId}/files`);
      if (fRes.ok) {
        const data = await fRes.json();
        setFiles(data);
        if (data.length > 0 && !activeFileId) {
          fetchFileContent(projectId, data[0].id);
        }
      }

      // Get Test Runs
      const testRes = await fetch(`${API_BASE}/projects/${projectId}/tests`);
      if (testRes.ok) {
        const data = await testRes.json();
        setTestRuns(data);
      }

      // Get Code Reviews
      const rRes = await fetch(`${API_BASE}/projects/${projectId}/reviews`);
      if (rRes.ok) {
        const data = await rRes.json();
        setReviews(data);
      }
    } catch (err) {
      console.error('Error fetching active project details:', err);
    }
  };

  // 3. Fetch specific file content
  const fetchFileContent = async (projectId, fileId) => {
    try {
      const res = await fetch(`${API_BASE}/projects/${projectId}/files/${fileId}/content`);
      if (res.ok) {
        const data = await res.json();
        setActiveFileId(fileId);
        setFileContent(data);
      }
    } catch (err) {
      console.error('Error reading file:', err);
    }
  };

  // 4. Create new Project
  const handleCreateProject = async (e) => {
    e.preventDefault();
    if (!newGoal.trim()) return;

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/projects`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal: newGoal, name: newName || null })
      });
      if (res.ok) {
        const data = await res.json();
        setNewGoal('');
        setNewName('');
        // Add to project list
        setProjects(prev => [data, ...prev]);
        setActiveProjectId(data.id);
      }
    } catch (err) {
      console.error('Error creating project:', err);
    } finally {
      setLoading(false);
    }
  };

  // 5. Control buttons (start, pause, resume, cancel)
  const handleControlAction = async (action) => {
    if (!activeProjectId) return;
    try {
      const res = await fetch(`${API_BASE}/projects/${activeProjectId}/${action}`, {
        method: 'POST'
      });
      if (res.ok) {
        fetchActiveProjectDetails(activeProjectId);
      }
    } catch (err) {
      console.error(`Error triggering ${action}:`, err);
    }
  };

  // 6. SSE Subscriber for Live Telemetry Events
  useEffect(() => {
    if (!activeProjectId) return;

    // Reset local events stream
    setEvents([]);

    // Close existing event source
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    // Open new event source
    const es = new EventSource(`${API_BASE}/projects/${activeProjectId}/events/stream`);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setEvents(prev => {
          // Prevent duplicates
          if (prev.some(e => e.id === data.id)) return prev;
          return [...prev, data];
        });
        
        // Refresh details (tasks, file count, etc.) when major events occur
        if (data.event_type.includes('COMPLETED') || data.event_type.includes('FAILED') || data.event_type.includes('CREATED')) {
          fetchActiveProjectDetails(activeProjectId);
        }
      } catch (err) {
        console.error('Error parsing SSE event:', err);
      }
    };

    es.onerror = () => {
      console.warn('SSE disconnected. Reconnecting...');
    };

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [activeProjectId]);

  // Periodic polling fallback for non-SSE components (every 4 seconds)
  useEffect(() => {
    if (!activeProjectId) return;
    
    // Initial fetch
    fetchActiveProjectDetails(activeProjectId);
    
    const interval = setInterval(() => {
      fetchActiveProjectDetails(activeProjectId);
    }, 4000);

    return () => clearInterval(interval);
  }, [activeProjectId]);

  // Auto-scroll logs
  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [events]);

  // Initial load
  useEffect(() => {
    fetchProjects();
    const interval = setInterval(fetchProjects, 10000);
    return () => clearInterval(interval);
  }, []);

  // Set first project active if list loads and none active
  useEffect(() => {
    if (projects.length > 0 && !activeProjectId) {
      setActiveProjectId(projects[0].id);
    }
  }, [projects]);

  const activeProject = projects.find(p => p.id === activeProjectId) || projectData;

  // Determine Agent color class for logs CSS
  const getAgentClass = (agentName) => {
    if (!agentName) return '';
    const name = agentName.toLowerCase();
    if (name.includes('projectmanager')) return 'pm';
    if (name.includes('requirements')) return 'req';
    if (name.includes('architect')) return 'arch';
    if (name.includes('database')) return 'db';
    if (name.includes('developer')) return 'dev';
    if (name.includes('testing')) return 'test';
    if (name.includes('codereview')) return 'review';
    if (name.includes('critic')) return 'critic';
    return '';
  };

  return (
    <div className="dashboard-container">
      {/* Header */}
      <header className="header">
        <div className="logo-section">
          <h1>DevForge AI <span>v0.1.0</span></h1>
        </div>
        <div>
          <button className="btn-secondary" onClick={fetchProjects}>Refresh Projects</button>
        </div>
      </header>

      {/* Main Layout */}
      <main className="main-layout">
        {/* Sidebar */}
        <aside className="sidebar">
          <div className="glass-panel" style={{ marginBottom: '20px' }}>
            <h3 style={{ marginBottom: '16px', fontWeight: 600 }}>Create New Project</h3>
            <form onSubmit={handleCreateProject}>
              <div className="form-group">
                <label>Project Name (Optional)</label>
                <input 
                  type="text" 
                  className="form-textarea" 
                  style={{ height: '40px' }} 
                  placeholder="e.g. Task API" 
                  value={newName} 
                  onChange={e => setNewName(e.target.value)} 
                />
              </div>
              <div className="form-group">
                <label>Goal / Requirement Description</label>
                <textarea 
                  className="form-textarea" 
                  placeholder="Build a REST API for a task management application with Postgres..."
                  value={newGoal} 
                  onChange={e => setNewGoal(e.target.value)} 
                  required
                />
              </div>
              <button type="submit" className="btn-primary" disabled={loading}>
                {loading ? 'Creating...' : 'START PROJECT'}
              </button>
            </form>
          </div>

          <h3 style={{ margin: '10px 0 12px 4px', fontWeight: 600 }}>Projects List</h3>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {projects.map(p => (
              <div 
                key={p.id} 
                className={`project-card ${p.id === activeProjectId ? 'active' : ''}`}
                onClick={() => {
                  setActiveProjectId(p.id);
                  setFileContent(null);
                  setActiveFileId(null);
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                  <strong style={{ fontSize: '14px' }}>{p.name}</strong>
                  <span className={`status-badge ${p.status.toLowerCase()}`}>{p.status}</span>
                </div>
                <p style={{ fontSize: '12px', color: 'var(--text-secondary)', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                  {p.goal}
                </p>
              </div>
            ))}
            {projects.length === 0 && (
              <p style={{ textAlign: 'center', color: 'var(--text-secondary)', marginTop: '20px' }}>
                No projects created yet.
              </p>
            )}
          </div>
        </aside>

        {/* Workspace */}
        <section className="workspace">
          {activeProject ? (
            <>
              {/* Project Title and Control Panel */}
              <div className="glass-panel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <h2 style={{ fontSize: '20px', fontWeight: 700, marginBottom: '6px' }}>{activeProject.name}</h2>
                  <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Goal: {activeProject.goal}</p>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div className="status-badge" style={{ fontSize: '12px', padding: '4px 10px', display: 'inline-block' }} className={`status-badge ${activeProject.status.toLowerCase()}`}>
                    Status: {activeProject.status}
                  </div>
                  
                  <div className="project-controls">
                    {activeProject.status === 'CREATED' && (
                      <button className="control-btn start" onClick={() => handleControlAction('start')}>START RUN</button>
                    )}
                    {activeProject.status === 'RUNNING' && (
                      <button className="control-btn pause" onClick={() => handleControlAction('pause')}>PAUSE</button>
                    )}
                    {activeProject.status === 'PAUSED' && (
                      <button className="control-btn resume" onClick={() => handleControlAction('resume')}>RESUME</button>
                    )}
                    {['RUNNING', 'PAUSED', 'CREATED'].includes(activeProject.status) && (
                      <button className="control-btn cancel" onClick={() => handleControlAction('cancel')}>CANCEL</button>
                    )}
                  </div>
                </div>
              </div>

              {/* Central Tabs & Actions */}
              <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: '400px' }}>
                <div className="tabs-header">
                  <button className={`tab-btn ${activeTab === 'graph' ? 'active' : ''}`} onClick={() => setActiveTab('graph')}>Task Graph</button>
                  <button className={`tab-btn ${activeTab === 'logs' ? 'active' : ''}`} onClick={() => setActiveTab('logs')}>Live Activity Feed</button>
                  <button className={`tab-btn ${activeTab === 'files' ? 'active' : ''}`} onClick={() => setActiveTab('files')}>Generated Workspace Files</button>
                  <button className={`tab-btn ${activeTab === 'tests' ? 'active' : ''}`} onClick={() => setActiveTab('tests')}>Test Results</button>
                  <button className={`tab-btn ${activeTab === 'reviews' ? 'active' : ''}`} onClick={() => setActiveTab('reviews')}>Code Review</button>
                </div>

                {/* Tab 1: Task Graph */}
                {activeTab === 'graph' && (
                  <div className="task-graph">
                    {tasks.map(t => (
                      <div key={t.id} className={`task-node ${t.status.toLowerCase()}`}>
                        <div className="task-node-header">
                          <span className="task-node-title">{t.title}</span>
                          <span className={`status-badge ${t.status.toLowerCase()}`}>{t.status}</span>
                        </div>
                        <p style={{ fontSize: '11px', color: 'var(--text-secondary)', margin: '8px 0' }}>{t.description}</p>
                        <div className="task-node-agent">
                          <span className={`agent-dot ${getAgentClass(t.assigned_agent)}`}></span>
                          <span>{t.assigned_agent}</span>
                        </div>
                        {t.attempts > 0 && (
                          <div style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '8px' }}>
                            Attempts: {t.attempts}/3
                          </div>
                        )}
                      </div>
                    ))}
                    {tasks.length === 0 && (
                      <div style={{ gridColumn: '1/-1', textAlign: 'center', padding: '40px 0', color: 'var(--text-secondary)' }}>
                        No tasks created yet. Click 'START RUN' to launch Project Manager.
                      </div>
                    )}
                  </div>
                )}

                {/* Tab 2: Live Activity Feed */}
                {activeTab === 'logs' && (
                  <div className="logs-panel" style={{ height: '400px' }}>
                    <div className="logs-container">
                      {events.map((e, idx) => (
                        <div key={e.id || idx} className={`log-line ${getAgentClass(e.agent)}`}>
                          [{new Date(e.created_at).toLocaleTimeString()}] <strong>{e.agent || 'SYSTEM'}:</strong> {e.message}
                          {e.payload && (
                            <pre style={{ background: 'rgba(0,0,0,0.3)', padding: '6px', marginTop: '4px', borderRadius: '4px', overflowX: 'auto', color: '#888' }}>
                              {JSON.stringify(e.payload, null, 2)}
                            </pre>
                          )}
                        </div>
                      ))}
                      {events.length === 0 && (
                        <p style={{ color: 'var(--text-secondary)', textAlign: 'center', marginTop: '40px' }}>
                          Waiting for agent events telemetry stream...
                        </p>
                      )}
                      <div ref={logsEndRef} />
                    </div>
                  </div>
                )}

                {/* Tab 3: Generated Workspace Files */}
                {activeTab === 'files' && (
                  <div className="file-view-layout">
                    <div className="file-list">
                      {files.map(f => (
                        <div 
                          key={f.id} 
                          className={`file-item ${f.id === activeFileId ? 'active' : ''}`}
                          onClick={() => fetchFileContent(activeProjectId, f.id)}
                        >
                          📄 {f.path}
                        </div>
                      ))}
                      {files.length === 0 && (
                        <p style={{ color: 'var(--text-secondary)', textAlign: 'center', marginTop: '20px' }}>
                          No files generated yet.
                        </p>
                      )}
                    </div>
                    <div className="code-viewer">
                      {fileContent ? (
                        <>
                          <div style={{ borderBottom: '1px solid rgba(255,255,255,0.1)', paddingBottom: '8px', marginBottom: '12px', color: '#818cf8', fontWeight: 600 }}>
                            Location: {fileContent.path}
                          </div>
                          <code>{fileContent.content}</code>
                        </>
                      ) : (
                        <p style={{ color: 'var(--text-secondary)', textAlign: 'center', marginTop: '100px' }}>
                          Select a file on the left side to view its source code.
                        </p>
                      )}
                    </div>
                  </div>
                )}

                {/* Tab 4: Test Results */}
                {activeTab === 'tests' && (
                  <div>
                    {testRuns.length > 0 ? (
                      <>
                        <div className="metrics-grid">
                          <div className="metric-card">
                            <label>Total Tests</label>
                            <div className="metric-val">{testRuns[0].total}</div>
                          </div>
                          <div className="metric-card">
                            <label>Passed</label>
                            <div className="metric-val pass">{testRuns[0].passed}</div>
                          </div>
                          <div className="metric-card">
                            <label>Failed</label>
                            <div className={`metric-val ${testRuns[0].failed > 0 ? 'fail' : ''}`}>{testRuns[0].failed}</div>
                          </div>
                          <div className="metric-card">
                            <label>Code Coverage</label>
                            <div className="metric-val" style={{ color: '#06b6d4' }}>{testRuns[0].coverage}%</div>
                          </div>
                        </div>

                        <div className="logs-panel" style={{ height: '280px' }}>
                          <h4 style={{ marginBottom: '8px', fontWeight: 600 }}>Sandbox Pytest Log Output</h4>
                          <div className="logs-container" style={{ whiteSpace: 'pre', fontSize: '13px' }}>
                            {testRuns[0].stdout}
                          </div>
                        </div>
                      </>
                    ) : (
                      <p style={{ color: 'var(--text-secondary)', textAlign: 'center', marginTop: '60px' }}>
                        No test run executions recorded yet.
                      </p>
                    )}
                  </div>
                )}

                {/* Tab 5: Code Review */}
                {activeTab === 'reviews' && (
                  <div>
                    {reviews.length > 0 ? (
                      <div>
                        <div className="metrics-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
                          <div className="metric-card">
                            <label>Review Status</label>
                            <div className={`metric-val ${reviews[0].status === 'FAIL' ? 'fail' : 'pass'}`}>{reviews[0].status}</div>
                          </div>
                          <div className="metric-card">
                            <label>Max Issue Severity</label>
                            <div className="metric-val" style={{ color: reviews[0].severity === 'HIGH' || reviews[0].severity === 'CRITICAL' ? 'var(--status-failed)' : 'var(--status-running)' }}>
                              {reviews[0].severity}
                            </div>
                          </div>
                        </div>

                        <h4 style={{ margin: '16px 0 8px 0', fontWeight: 600 }}>Detected Issues</h4>
                        <div style={{ background: 'rgba(0,0,0,0.2)', padding: '16px', borderRadius: '8px', border: '1px solid var(--border-color)', marginBottom: '20px' }}>
                          {reviews[0].issues && reviews[0].issues.map((issue, idx) => (
                            <div key={idx} style={{ padding: '8px 0', borderBottom: idx < reviews[0].issues.length - 1 ? '1px solid rgba(255,255,255,0.05)' : 'none' }}>
                              <span className="status-badge failed" style={{ marginRight: '8px' }}>{issue.severity}</span>
                              <span>{issue.description}</span>
                            </div>
                          ))}
                          {(!reviews[0].issues || reviews[0].issues.length === 0) && (
                            <p style={{ color: 'var(--text-secondary)' }}>No issues detected. Code satisfies quality benchmarks.</p>
                          )}
                        </div>

                        <h4 style={{ margin: '16px 0 8px 0', fontWeight: 600 }}>Recommendations</h4>
                        <ul style={{ paddingLeft: '20px', color: 'var(--text-secondary)' }}>
                          {reviews[0].recommendations && reviews[0].recommendations.map((rec, idx) => (
                            <li key={idx} style={{ marginBottom: '6px' }}>{rec}</li>
                          ))}
                        </ul>
                      </div>
                    ) : (
                      <p style={{ color: 'var(--text-secondary)', textAlign: 'center', marginTop: '60px' }}>
                        No code reviews logged yet.
                      </p>
                    )}
                  </div>
                )}

              </div>
            </>
          ) : (
            <div className="glass-panel" style={{ textAlign: 'center', padding: '100px 0' }}>
              <h2 style={{ fontSize: '24px', fontWeight: 700, marginBottom: '12px' }}>Welcome to DevForge AI</h2>
              <p style={{ color: 'var(--text-secondary)', maxWidth: '500px', margin: '0 auto' }}>
                Select a project on the left side or enter a new goal statement to spin up your autonomous agent team!
              </p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

export default App;
