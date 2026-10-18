import { useCallback, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Bot,
  ChevronDown,
  Clock3,
  Database,
  GitBranch,
  History,
  LayoutDashboard,
  Menu,
  Moon,
  Network,
  Play,
  Plus,
  Search,
  Settings,
  ShieldCheck,
  Sun,
  TriangleAlert,
  Terminal,
  RotateCcw,
  Workflow,
} from "lucide-react";
import { api, getToken } from "./api";
import type { Entity, Run, Step, Graph, GraphNode, Overview } from "./types";
import ExecutionGraph from "./components/ExecutionGraph";
import Inspector from "./components/Inspector";
import CreateRun from "./components/CreateRun";
import SettingsPanel from "./components/SettingsPanel";
import {
  RunSelector,
  RunBar,
  ActivityList,
  AgentList,
  Empty,
} from "./components/Shared";

const navigation = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "graph", label: "Execution graph", icon: Network },
  { id: "agents", label: "Agent activity", icon: Bot },
  { id: "failures", label: "Failure investigation", icon: TriangleAlert },
  { id: "memory", label: "Memory explorer", icon: BookOpen },
  { id: "history", label: "Run history", icon: History },
];
const titles: Record<string, [string, string]> = {
  overview: [
    "Execution overview",
    "A clear view of what your agents know, do, and verify.",
  ],
  graph: [
    "Execution graph",
    "Follow every action back to the evidence behind it.",
  ],
  agents: ["Agent activity", "Cooperating roles, one shared execution memory."],
  failures: [
    "Failure investigation",
    "Understand what failed and how the system recovered.",
  ],
  memory: [
    "Memory explorer",
    "Recall verified knowledge and the paths that support it.",
  ],
  history: [
    "Run history",
    "Persistent goals, checkpoints, and a safe path forward.",
  ],
  settings: [
    "Workspace settings",
    "Connection health and execution configuration.",
  ],
};
const sum = (v: Record<string, number> = {}) =>
  Object.values(v).reduce((a, b) => a + b, 0);
const time = (v: unknown) =>
  typeof v === "number"
    ? new Date(v).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "—";
const date = (v: unknown) =>
  typeof v === "number" ? new Date(v).toLocaleString() : "—";
const label = (v: unknown) => String(v ?? "unknown").replaceAll("_", " ");

export default function App() {
  const client = useQueryClient();
  const [page, setPage] = useState(() =>
    titles[location.hash.slice(1)] ? location.hash.slice(1) : "overview",
  );
  const [runId, setRunId] = useState("");
  const [modal, setModal] = useState(false);
  const closeModal = useCallback(() => setModal(false), []);
  const [mobile, setMobile] = useState(false);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [highlight, setHighlight] = useState<string[]>([]);
  const [dark, setDark] = useState(
    localStorage.getItem("agenttrace-theme") !== "light",
  );
  const [stream, setStream] = useState("Connecting");
  const [actionError, setActionError] = useState("");
  const [memoryQuery, setMemoryQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  useEffect(() => {
    const change = () => {
      const next = location.hash.slice(1) || "overview";
      if (!titles[next]) return;
      setPage(next);
      setMobile(false);
      setSelected(null);
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    localStorage.setItem("agenttrace-theme", dark ? "dark" : "light");
  }, [dark]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let refresh: ReturnType<typeof setTimeout> | undefined;
    let cursor = Number(sessionStorage.getItem("agenttrace-cursor") || 0);
    async function connect() {
      try {
        const res = await fetch("/api/events/stream?after=" + cursor, {
          headers: { Authorization: "Bearer " + getToken() },
          signal: controller.signal,
        });
        if (!res.ok || !res.body) throw Error("Stream unavailable");
        setStream("Connected");
        client.invalidateQueries();
        const reader = res.body.getReader(),
          decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let end = buffer.indexOf("\n\n");
          while (end >= 0) {
            const chunk = buffer.slice(0, end);
            buffer = buffer.slice(end + 2);
            const data = chunk
              .split("\n")
              .find((line) => line.startsWith("data: "));
            if (data) {
              const event = JSON.parse(data.slice(6));
              if (typeof event.occurred_at === "number") {
                cursor = Math.max(cursor, event.occurred_at);
                sessionStorage.setItem("agenttrace-cursor", String(cursor));
              }
              if (!refresh)
                refresh = setTimeout(() => {
                  client.invalidateQueries();
                  refresh = undefined;
                }, 150);
            }
            end = buffer.indexOf("\n\n");
          }
        }
      } catch {
        if (controller.signal.aborted) return;
        setStream("Reconnecting");
      }
      if (!controller.signal.aborted) timer = setTimeout(connect, 3000);
    }
    connect();
    return () => {
      controller.abort();
      clearTimeout(timer);
      clearTimeout(refresh);
    };
  }, [client]);
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => api<Run[]>("/runs"),
  });
  const overview = useQuery({
    queryKey: ["overview"],
    queryFn: () => api<Overview>("/overview"),
  });
  const config = useQuery({
    queryKey: ["config"],
    queryFn: () => api<Entity>("/config/status"),
  });
  const activeId = runId || runs.data?.[0]?.id || "";
  const activeRun = runs.data?.find((r) => r.id === activeId);
  const graph = useQuery({
    queryKey: ["graph", activeId],
    queryFn: () => api<Graph>("/runs/" + activeId + "/graph"),
    enabled: !!activeId,
  });
  const steps = useQuery({
    queryKey: ["steps", activeId],
    queryFn: () => api<Step[]>("/runs/" + activeId + "/steps"),
    enabled: !!activeId,
  });
  const decisions = useQuery({
    queryKey: ["decisions", activeId],
    queryFn: () => api<Entity[]>("/runs/" + activeId + "/explanations"),
    enabled: !!activeId,
  });
  const agents = useQuery({
    queryKey: ["agents"],
    queryFn: () => api<Entity[]>("/agents"),
  });
  const memories = useQuery({
    queryKey: ["memory", submittedQuery, activeId],
    queryFn: () =>
      api<{ type: string; record: Entity }[]>(
        "/memory/search?query=" +
          encodeURIComponent(submittedQuery) +
          "&run_id=" +
          activeId,
      ),
    enabled: page === "memory",
  });
  const checkpoint = useQuery({
    queryKey: ["checkpoint", activeId],
    queryFn: () => api<Entity | null>("/runs/" + activeId + "/checkpoint"),
    enabled: !!activeId,
  });
  const action = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      api("/runs/" + id + "/" + name, {}),
    onSuccess: () => {
      setActionError("");
      client.invalidateQueries();
    },
    onError: (e) => setActionError(e.message),
  });
  const currentSelected = selected
    ? graph.data?.nodes.find((n) => n.id === selected.id) || selected
    : null;
  const go = (id: string) => {
    location.hash = id;
  };
  const selectRun = (id: string) => {
    setRunId(id);
    setSelected(null);
    setHighlight([]);
  };
  const failedNodes =
    graph.data?.nodes.filter((n) => n.label === "Failure") || [];
  const v = overview.data;
  const progress = steps.data?.length
    ? Math.round(
        (steps.data.filter((s) => s.status === "succeeded").length /
          steps.data.length) *
          100,
      )
    : 0;
  function showNode(n: GraphNode) {
    setSelected(n);
  }
  const graphView = graph.data ? (
    <ExecutionGraph
      graph={graph.data}
      onSelect={showNode}
      highlight={highlight}
    />
  ) : (
    <Empty
      icon={Network}
      title="Your execution graph starts here"
      text="Create a run to see real tasks, dependencies, and evidence in FalkorDB."
      action={() => setModal(true)}
    />
  );
  return (
    <div className="app-layout">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className={"sidebar " + (mobile ? "open" : "")}>
        <a className="brand" href="#overview">
          <div className="brand-mark">
            <Workflow size={23} />
          </div>
          <span>
            AgentTrace<span className="brand-period">.</span>
          </span>
        </a>
        <button className="workspace-switch" onClick={() => go("settings")}>
          <span className="workspace-avatar">A</span>
          <span>
            Local workspace<small>Developer environment</small>
          </span>
          <ChevronDown size={14} />
        </button>
        <p className="nav-caption">WORKSPACE</p>
        <nav aria-label="Main navigation">
          {navigation.map((n) => (
            <a
              href={"#" + n.id}
              key={n.id}
              className={page === n.id ? "active" : ""}
            >
              <n.icon size={18} />
              <span>{n.label}</span>
              {n.id === "failures" && !!v?.failed_attempts && (
                <span className="nav-count">{v.failed_attempts}</span>
              )}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="graph-native">
            <Database size={18} />
            <strong>Memory that persists.</strong>
            <p>
              Every action, connected.
              <br />
              Powered by FalkorDB.
            </p>
            <span>
              <i className={"dot " + (config.data ? "teal" : "amber")} />
              {config.data ? "Graph connected" : "Checking connection"}
            </span>
          </div>
          <a
            className={"settings-link " + (page === "settings" ? "active" : "")}
            href="#settings"
          >
            <Settings size={18} />
            Settings
          </a>
          <button className="theme-button" onClick={() => setDark(!dark)}>
            {dark ? <Sun size={17} /> : <Moon size={17} />}{" "}
            {dark ? "Light appearance" : "Dark appearance"}
          </button>
          <div className="local-user">
            <span className="user-avatar">D</span>
            <div>
              Demo tenant<small>Local development</small>
            </div>
            <span className="badge neutral">LOCAL</span>
          </div>
        </div>
      </aside>
      <div className="main-layout">
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              className="mobile-menu icon-button"
              aria-label="Toggle navigation"
              onClick={() => setMobile(!mobile)}
            >
              <Menu size={20} />
            </button>
            <span>Workspace</span>
            <span className="slash">/</span>
            <strong>{titles[page]?.[0] || "Overview"}</strong>
          </div>
          <div className="topbar-right">
            <span className="connection">
              <i
                className={"dot " + (stream === "Connected" ? "teal" : "amber")}
              />
              {stream === "Connected" ? "Live updates" : stream}
            </span>
            <a href="/docs" target="_blank" rel="noreferrer">
              <BookOpen size={15} /> API docs
            </a>
            <span className="user-avatar small">D</span>
          </div>
        </header>
        <main id="main" tabIndex={-1}>
          <div className="page-heading">
            <div>
              <div className="eyebrow accent">AGENT MEMORY & COORDINATION</div>
              <h1>{titles[page]?.[0] || "Overview"}</h1>
              <p>{titles[page]?.[1]}</p>
            </div>
            <button className="primary" onClick={() => setModal(true)}>
              <Plus size={17} /> New agent run
            </button>
          </div>
          {(runs.error || overview.error || actionError) && (
            <div className="error-banner" role="alert">
              <TriangleAlert size={18} />
              {actionError || runs.error?.message || overview.error?.message}
              <button onClick={() => client.invalidateQueries()}>Retry</button>
            </div>
          )}
          <div className="mode-banner">
            <div>
              <Terminal size={16} />
              <strong>
                {activeRun?.mode === "llm"
                  ? "Live model planner"
                  : "Deterministic demo"}
              </strong>
              <span>
                {activeRun?.mode === "llm"
                  ? "Model-generated plan. Registered tools and approved recovery."
                  : "Real tools. Real graph state. Fixed planning and approved recovery."}
              </span>
            </div>
            <span className="badge neutral">
              {activeRun?.mode === "llm"
                ? "CONSTRAINED LOCAL EXECUTION"
                : "NO LIVE MODEL REASONING"}
            </span>
          </div>
          {page === "overview" && (
            <>
              <div className="stats-grid">
                {[
                  {
                    title: "Total runs",
                    value: sum(v?.runs),
                    icon: Workflow,
                    note: (v?.runs.running || 0) + " currently active",
                    color: "teal",
                  },
                  {
                    title: "Verified steps",
                    value: v?.steps.succeeded || 0,
                    icon: ShieldCheck,
                    note: "Independently checked",
                    color: "blue",
                  },
                  {
                    title: "Pending steps",
                    value: (v?.steps.pending || 0) + (v?.steps.retryable || 0),
                    icon: Clock3,
                    note:
                      (v?.dependency_blocked || 0) + " waiting on dependencies",
                    color: "amber",
                  },
                  {
                    title: "Recovered failures",
                    value: v?.recoveries || 0,
                    icon: RotateCcw,
                    note: (v?.failed_attempts || 0) + " recorded failures",
                    color: "purple",
                  },
                ].map((s) => (
                  <div className="stat-card" key={s.title}>
                    <div>
                      <span>{s.title}</span>
                      <s.icon size={18} className={s.color + "-text"} />
                    </div>
                    <strong>{overview.isPending ? "—" : s.value}</strong>
                    <p>{s.note}</p>
                  </div>
                ))}
              </div>
              <div className="section-heading">
                <div>
                  <h2>
                    Current execution{" "}
                    <span className="badge neutral">GRAPH NATIVE</span>
                  </h2>
                  <p>Every task has a history. Every decision has a reason.</p>
                </div>
                <button onClick={() => go("graph")}>
                  Open full graph <ArrowRight size={15} />
                </button>
              </div>
              {activeRun && (
                <RunBar
                  run={activeRun}
                  progress={progress}
                  pending={action.isPending}
                  onAction={(name) => action.mutate({ id: activeId, name })}
                  select={
                    <RunSelector
                      runs={runs.data || []}
                      value={activeId}
                      onChange={selectRun}
                    />
                  }
                />
              )}
              <div className="overview-graph">{graphView}</div>
              <div className="overview-bottom">
                <section className="panel">
                  <div className="panel-heading">
                    <h2>Recent activity</h2>
                    <span className="subtle">Persisted events</span>
                  </div>
                  <ActivityList events={v?.recent_events || []} />
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <h2>Agent team</h2>
                    <button onClick={() => go("agents")}>
                      View all <ArrowRight size={14} />
                    </button>
                  </div>
                  <AgentList agents={agents.data || []} />
                </section>
              </div>
            </>
          )}
          {page === "graph" && (
            <>
              {activeRun && (
                <RunBar
                  run={activeRun}
                  progress={progress}
                  pending={action.isPending}
                  onAction={(name) => action.mutate({ id: activeId, name })}
                  select={
                    <RunSelector
                      runs={runs.data || []}
                      value={activeId}
                      onChange={selectRun}
                    />
                  }
                />
              )}
              <div className="graph-and-details">
                <div className="full-graph">{graphView}</div>
                {currentSelected && (
                  <Inspector
                    node={currentSelected}
                    onClose={() => setSelected(null)}
                    onHighlight={(ids) => {
                      setHighlight(ids);
                    }}
                  />
                )}
              </div>
              <div className="section-heading">
                <div>
                  <h2>Decision evidence</h2>
                  <p>Recorded when the action was selected.</p>
                </div>
                <span className="subtle">
                  Click a decision to inspect its sources
                </span>
              </div>
              <div className="decision-grid">
                {decisions.data?.map((d) => (
                  <button
                    className="decision-card"
                    key={d.id}
                    onClick={() => {
                      const node = graph.data?.nodes.find((n) => n.id === d.id);
                      if (node) setSelected(node);
                    }}
                  >
                    <div>
                      <GitBranch size={16} />
                      <span>{label(d.decision_type)}</span>
                      <span className="subtle">{time(d.created_at)}</span>
                    </div>
                    <strong>{label(d.action)}</strong>
                    <p>{String(d.rationale_summary)}</p>
                    <span className="evidence-label">
                      {label(d.evidence_status)} <ArrowRight size={13} />
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}
          {page === "agents" && (
            <>
              <div className="section-heading">
                <h2>Shared graph, specialized roles</h2>
                <span className="subtle">
                  {agents.data?.length || 0} registered agents
                </span>
              </div>
              <div className="agent-grid">
                {agents.data?.map((a) => (
                  <div className="panel agent-card" key={a.id}>
                    <div className="agent-card-icon">
                      <Bot size={23} />
                    </div>
                    <span
                      className={
                        "badge " +
                        (Number(a.last_heartbeat_at) > Date.now() - 30000
                          ? String(a.status)
                          : "neutral")
                      }
                    >
                      {Number(a.last_heartbeat_at) > Date.now() - 30000
                        ? label(a.status)
                        : "last seen"}
                    </span>
                    <h2>{String(a.name)}</h2>
                    <p>{label(a.role)} agent</p>
                    <div className="kv">
                      <span>Last heartbeat</span>
                      <code>{time(a.last_heartbeat_at)}</code>
                    </div>
                    <div className="kv">
                      <span>Assignment</span>
                      <code>
                        {a.current_step_id
                          ? String(a.current_step_id).slice(0, 8)
                          : "None"}
                      </code>
                    </div>
                  </div>
                ))}
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <h2>Coordination timeline</h2>
                  <span className="subtle">Actual events only</span>
                </div>
                <ActivityList
                  events={
                    v?.recent_events.filter((e) =>
                      [
                        "agent_handoff",
                        "task_claimed",
                        "attempt_started",
                        "verification_started",
                      ].includes(String(e.event_type)),
                    ) || []
                  }
                />
              </section>
            </>
          )}
          {page === "failures" && (
            <>
              <div className="section-heading">
                <h2>Failure history</h2>
                <RunSelector
                  runs={runs.data || []}
                  value={activeId}
                  onChange={selectRun}
                />
              </div>
              {failedNodes.length ? (
                <div className="failure-layout">
                  <div>
                    {failedNodes.map((n) => (
                      <button
                        key={n.id}
                        className="panel failure-card"
                        onClick={() => {
                          const attempt = graph.data?.edges.find(
                            (e) =>
                              e.target === n.id && e.label === "CAUSED_FAILURE",
                          );
                          const edge = graph.data?.edges.find(
                            (e) =>
                              e.target === attempt?.source &&
                              e.label === "HAS_ATTEMPT",
                          );
                          const step = graph.data?.nodes.find(
                            (s) => s.id === edge?.source,
                          );
                          setSelected(step || n);
                        }}
                      >
                        <div>
                          <TriangleAlert size={19} />
                          <span
                            className={
                              "badge " +
                              (n.properties.resolved_at
                                ? "succeeded"
                                : "failed")
                            }
                          >
                            {n.properties.resolved_at
                              ? "Verified recovery"
                              : "Unresolved"}
                          </span>
                        </div>
                        <h2>{label(n.properties.error_code)}</h2>
                        <p>{String(n.properties.root_cause)}</p>
                        <span className="subtle">
                          {date(n.properties.discovered_at)}
                        </span>
                        <span className="evidence-label">
                          Inspect attempts and dependency impact{" "}
                          <ArrowRight size={14} />
                        </span>
                      </button>
                    ))}
                  </div>
                  {currentSelected && (
                    <Inspector
                      node={currentSelected}
                      onClose={() => setSelected(null)}
                      onHighlight={(ids) => {
                        setHighlight(ids);
                        go("graph");
                      }}
                    />
                  )}
                </div>
              ) : (
                <Empty
                  icon={ShieldCheck}
                  title="No failures recorded in this run"
                  text="Failure records appear here when real execution or verification fails."
                />
              )}
            </>
          )}
          {page === "memory" && (
            <>
              <form
                className="memory-search"
                onSubmit={(e) => {
                  e.preventDefault();
                  setSubmittedQuery(memoryQuery);
                }}
              >
                <Search size={21} />
                <label className="sr-only" htmlFor="memory-query">
                  Search graph memory
                </label>
                <input
                  id="memory-query"
                  value={memoryQuery}
                  onChange={(e) => setMemoryQuery(e.target.value)}
                  placeholder="Search learned facts, past actions, or recovery procedures…"
                />
                <button className="primary" type="submit">
                  Search memory
                </button>
              </form>
              <div className="section-heading">
                <div>
                  <h2>Connected knowledge</h2>
                  <p>
                    Verified facts → applicable procedures → recent episodes.
                  </p>
                </div>
                <RunSelector
                  runs={runs.data || []}
                  value={activeId}
                  onChange={selectRun}
                />
              </div>
              <div className="memory-grid">
                {memories.data?.map(({ type, record: r }) => (
                  <article className="panel memory-card" key={r.id}>
                    <div>
                      <BookOpen size={17} />
                      <span className="eyebrow">{type}</span>
                      <span
                        className={
                          "badge " +
                          (r.status === "verified" ? "succeeded" : "neutral")
                        }
                      >
                        {label(r.status || "recorded")}
                      </span>
                    </div>
                    <h2>
                      {String(r.name || r.subject || r.event_type).replaceAll(
                        "_",
                        " ",
                      )}
                    </h2>
                    <p>{String(r.value || r.summary || r.problem_signature)}</p>
                    <code className="record-id">
                      {String(r.source_reference || r.id)}
                    </code>
                    {r.instructions_json && (
                      <pre>{String(r.instructions_json)}</pre>
                    )}
                  </article>
                ))}
              </div>
              {memories.data?.length === 0 && (
                <Empty
                  icon={BookOpen}
                  title="No matching memory"
                  text="Complete a run to learn verified facts and recovery procedures."
                />
              )}
            </>
          )}
          {page === "history" && (
            <>
              <section className="panel run-table">
                <div className="panel-heading">
                  <h2>Persistent runs</h2>
                  <span className="subtle">
                    {runs.data?.length || 0} runs · Latest 50
                  </span>
                </div>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Goal / run</th>
                        <th>Status</th>
                        <th>Mode</th>
                        <th>Created</th>
                        <th>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {runs.data?.map((r) => (
                        <tr key={r.id}>
                          <td>
                            <button
                              className="table-goal"
                              onClick={() => {
                                selectRun(r.id);
                                go("graph");
                              }}
                            >
                              {r.goal}
                            </button>
                            <code>{r.id.slice(0, 8)}</code>
                          </td>
                          <td>
                            <span className={"badge " + r.status}>
                              {label(r.status)}
                            </span>
                          </td>
                          <td>
                            {r.mode === "demo"
                              ? "Deterministic"
                              : "Live planner"}
                          </td>
                          <td>{date(r.created_at)}</td>
                          <td>
                            {[
                              "planned",
                              "paused",
                              "interrupted",
                              "running",
                            ].includes(r.status) ? (
                              <button
                                disabled={action.isPending}
                                onClick={() =>
                                  action.mutate({
                                    id: r.id,
                                    name:
                                      r.status === "planned"
                                        ? "start"
                                        : "resume",
                                  })
                                }
                              >
                                <Play size={14} />
                                {r.status === "planned" ? "Start" : "Resume"}
                              </button>
                            ) : (
                              <button
                                onClick={() => {
                                  selectRun(r.id);
                                  go("graph");
                                }}
                              >
                                Inspect <ArrowRight size={14} />
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
              {checkpoint.data && (
                <section className="panel checkpoint">
                  <div>
                    <ArrowDownToLine size={23} />
                    <h2>Latest checkpoint</h2>
                  </div>
                  <p>
                    Version {String(checkpoint.data.version)} ·{" "}
                    {date(checkpoint.data.created_at)}
                  </p>
                  <p className="subtle">
                    {String(checkpoint.data.current_goal)}
                  </p>
                  <code>{checkpoint.data.id}</code>
                </section>
              )}
            </>
          )}
          {page === "settings" && (
            <SettingsPanel
              config={config.data}
              onRefresh={() => client.invalidateQueries()}
            />
          )}
          <footer className="page-footer">
            <span>
              <Database size={13} /> FalkorDB is the source of truth
            </span>
            <span>AgentTrace · Graph Hacks 2026</span>
          </footer>
        </main>
      </div>
      {page === "overview" && currentSelected && (
        <div className="drawer-wrap">
          <button
            className="drawer-backdrop"
            aria-label="Close record details"
            onClick={() => setSelected(null)}
          />
          <Inspector
            node={currentSelected}
            onClose={() => setSelected(null)}
            onHighlight={(ids) => {
              setHighlight(ids);
              go("graph");
            }}
          />
        </div>
      )}
      {modal && (
        <CreateRun
          onClose={closeModal}
          configured={!!config.data?.llm_configured}
          onCreated={(id) => {
            setModal(false);
            selectRun(id);
            go("graph");
            client.invalidateQueries();
          }}
        />
      )}
    </div>
  );
}
