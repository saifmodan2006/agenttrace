import {
  Workflow,
  Pause,
  Play,
  CheckCircle2,
  Activity,
  ShieldCheck,
  TriangleAlert,
  Bot,
  Network,
  Plus,
} from "lucide-react";
import type { Entity, Run } from "../types";
const time = (v: unknown) =>
  typeof v === "number"
    ? new Date(v).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "�";
const label = (v: unknown) => String(v ?? "unknown").replaceAll("_", " ");

export function RunSelector({
  runs,
  value,
  onChange,
}: {
  runs: Run[];
  value: string;
  onChange: (s: string) => void;
}) {
  return (
    <select
      className="run-selector"
      aria-label="Select run"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {runs.map((r) => (
        <option key={r.id} value={r.id}>
          {r.goal.slice(0, 55)}
        </option>
      ))}
    </select>
  );
}
export function RunBar({
  run,
  progress,
  pending,
  onAction,
  select,
}: {
  run: Run;
  progress: number;
  pending: boolean;
  onAction: (s: string) => void;
  select: React.ReactNode;
}) {
  return (
    <div className="run-bar">
      <div className="run-ident">
        <span className="run-icon">
          <Workflow size={18} />
        </span>
        <div>
          {select}
          <div className="run-meta">
            <code>{run.id.slice(0, 8)}</code>
            <span>·</span>
            <span>
              {run.mode === "demo" ? "Deterministic demo" : "Live LLM planner"}
            </span>
            <span className={"badge " + run.status}>{label(run.status)}</span>
          </div>
        </div>
      </div>
      <div className="run-controls">
        <div className="progress-group">
          <span>{progress}% verified</span>
          <div className="progress">
            <i style={{ width: progress + "%" }} />
          </div>
        </div>
        {run.status === "running" ? (
          <button disabled={pending} onClick={() => onAction("pause")}>
            <Pause size={14} />
            Pause
          </button>
        ) : ["planned", "paused", "interrupted"].includes(run.status) ? (
          <button
            disabled={pending}
            onClick={() =>
              onAction(run.status === "planned" ? "start" : "resume")
            }
          >
            <Play size={14} />
            {run.status === "planned" ? "Start run" : "Resume"}
          </button>
        ) : (
          <span className="teal-text">
            <CheckCircle2 size={18} />
          </span>
        )}
      </div>
    </div>
  );
}
export function ActivityList({ events }: { events: Entity[] }) {
  return (
    <div className="activity-list">
      {events.length ? (
        events.map((e) => (
          <div className="activity-item" key={e.id}>
            <span
              className={
                "activity-icon " +
                (String(e.event_type).includes("fail")
                  ? "amber-text"
                  : "teal-text")
              }
            >
              {String(e.event_type).includes("verification") ? (
                <ShieldCheck size={15} />
              ) : String(e.event_type).includes("fail") ? (
                <TriangleAlert size={15} />
              ) : (
                <Activity size={15} />
              )}
            </span>
            <div>
              <strong>{label(e.event_type)}</strong>
              <p>{String(e.summary)}</p>
            </div>
            <time>{time(e.occurred_at)}</time>
          </div>
        ))
      ) : (
        <div className="small-empty">
          Your agents’ activity will appear here after you start a run.
        </div>
      )}
    </div>
  );
}
export function AgentList({ agents }: { agents: Entity[] }) {
  return (
    <div className="agent-list">
      {agents.length ? (
        agents.map((a) => (
          <div className="agent-row" key={a.id}>
            <span className="agent-avatar">
              <Bot size={18} />
            </span>
            <div>
              <strong>{String(a.name)}</strong>
              <small>{label(a.role)}</small>
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
          </div>
        ))
      ) : (
        <div className="small-empty">Agents register when a worker starts.</div>
      )}
    </div>
  );
}
export function Empty({
  icon: Icon,
  title,
  text,
  action,
}: {
  icon: typeof Network;
  title: string;
  text: string;
  action?: () => void;
}) {
  return (
    <div className="empty-state">
      <div className="empty-graphic">
        <Icon size={34} />
      </div>
      <h2>{title}</h2>
      <p>{text}</p>
      {action && (
        <button className="primary" onClick={action}>
          <Plus size={16} />
          Create your first run
        </button>
      )}
    </div>
  );
}
