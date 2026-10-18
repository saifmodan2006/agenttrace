import { useState } from "react";
import {
  Database,
  Settings,
  ShieldCheck,
  RotateCcw,
  Check,
  Radio,
  ArrowRight,
} from "lucide-react";
import { getToken } from "../api";
import type { Entity } from "../types";

export default function SettingsPanel({
  config,
  onRefresh,
}: {
  config?: Entity;
  onRefresh: () => void;
}) {
  const [token, setToken] = useState(getToken());
  const [saved, setSaved] = useState(false);
  return (
    <div className="settings-grid">
      <section className="panel settings-panel">
        <h2>
          <Database size={20} /> Connections
        </h2>
        <div className="setting-row">
          <div>
            <strong>FalkorDB</strong>
            <p>Authoritative persistent graph database</p>
          </div>
          <span className={"badge " + (config ? "succeeded" : "failed")}>
            {String(config?.database || "unknown")}
          </span>
        </div>
        <div className="setting-row">
          <div>
            <strong>Language model</strong>
            <p>
              {String(
                config?.llm_model ||
                  "Set LLM_BASE_URL and LLM_MODEL on the server",
              )}
            </p>
          </div>
          <span className="badge neutral">
            {config?.llm_configured ? "Configured" : "Not configured"}
          </span>
        </div>
        <div className="setting-row">
          <div>
            <strong>Tool execution</strong>
            <p>Allowlisted subprocesses in isolated demo directories</p>
          </div>
          <ShieldCheck size={20} className="teal-text" />
        </div>
        <button onClick={onRefresh}>
          <RotateCcw size={15} /> Check connections
        </button>
      </section>
      <section className="panel settings-panel">
        <h2>
          <Settings size={20} /> Worker configuration
        </h2>
        <div className="kv">
          <span>Lease duration</span>
          <code>{String(config?.lease_ms || "—")} ms</code>
        </div>
        <div className="kv">
          <span>Scheduling interval</span>
          <code>{String(config?.worker_poll_seconds || "—")} s</code>
        </div>
        <div className="kv">
          <span>Default mode</span>
          <span className="badge neutral">Deterministic demo</span>
        </div>
        <div className="retention">
          <strong>History retention</strong>
          <p>{String(config?.retention || "Loading…")}</p>
        </div>
      </section>
      <section className="panel settings-panel">
        <h2>
          <ShieldCheck size={20} /> Tenant access
        </h2>
        <p className="subtle">
          Token stays in this browser session. Production deployments must
          replace the local demo credentials.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            sessionStorage.setItem("agenttrace-token", token);
            sessionStorage.removeItem("agenttrace-cursor");
            setSaved(true);
            location.reload();
          }}
        >
          <label htmlFor="tenant-token">Tenant bearer token</label>
          <input
            id="tenant-token"
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            autoComplete="off"
          />
          <button type="submit">
            {saved ? <Check size={15} /> : <ShieldCheck size={15} />} Save
            session token
          </button>
        </form>
      </section>
      <section className="panel settings-panel">
        <h2>
          <Radio size={20} /> About this demo
        </h2>
        <p className="subtle">
          Planner, executor, verifier, and recovery roles share a FalkorDB
          graph. The included recovery is deterministic and pre-approved. No
          cloud account or model key is needed.
        </p>
        <a className="text-link" href="/docs" target="_blank" rel="noreferrer">
          Explore the OpenAPI documentation <ArrowRight size={15} />
        </a>
      </section>
    </div>
  );
}
