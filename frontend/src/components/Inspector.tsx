import { useQuery } from "@tanstack/react-query";
import {
  X,
  ExternalLink,
  ShieldCheck,
  ArrowRight,
  AlertTriangle,
} from "lucide-react";
import { api } from "../api";
import type { Entity, GraphNode, Impact, Explanation } from "../types";

export default function Inspector({
  node,
  onClose,
  onHighlight,
}: {
  node: GraphNode;
  onClose: () => void;
  onHighlight: (ids: string[]) => void;
}) {
  const p = node.properties;
  const isStep = node.label === "Step";
  const attempts = useQuery({
    queryKey: ["attempts", p.id],
    queryFn: () => api<Entity[]>("/steps/" + p.id + "/attempts"),
    enabled: isStep,
  });
  const failures = useQuery({
    queryKey: ["failures", p.id],
    queryFn: () => api<Entity[]>("/steps/" + p.id + "/failures"),
    enabled: isStep,
  });
  const impact = useQuery({
    queryKey: ["impact", p.id],
    queryFn: () => api<Impact>("/steps/" + p.id + "/impact"),
    enabled: isStep,
  });
  const explanation = useQuery({
    queryKey: ["decision", p.id],
    queryFn: () => api<Explanation>("/decisions/" + p.id),
    enabled: node.label === "Decision",
  });
  return (
    <aside className="inspector" aria-label="Graph record details">
      <div className="panel-heading">
        <span className="eyebrow">{node.label} DETAILS</span>
        <button
          className="icon-button"
          aria-label="Close details"
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </div>
      <h2>{String(p.title || p.name || p.action || p.goal || node.label)}</h2>
      <code className="record-id">{p.id}</code>
      <div className="detail-summary">
        <span className={"badge " + String(p.status || "recorded")}>
          {String(p.status || "recorded").replaceAll("_", " ")}
        </span>
        <p>
          {String(
            p.objective ||
              p.rationale_summary ||
              p.description ||
              p.summary ||
              "Persisted graph record",
          )}
        </p>
      </div>
      {isStep && (
        <>
          <h3>
            <ShieldCheck size={15} /> Verification
          </h3>
          <p>
            {String(p.verification_status)} · {Number(p.attempt_count)} attempts
          </p>
          <p className="subtle">
            Tool: <code>{p.tool_name}</code>
          </p>
          {impact.data && (
            <div className="impact-box">
              <h3>
                <AlertTriangle size={15} /> Dependency impact
              </h3>
              <p>
                {impact.data.directly_blocked.length} direct ·{" "}
                {impact.data.transitively_affected.length} transitive paths
              </p>
              <button
                onClick={() =>
                  onHighlight([
                    ...new Set([
                      p.id,
                      ...impact.data!.transitively_affected.flatMap(
                        (a) => a.path,
                      ),
                    ]),
                  ])
                }
              >
                Highlight dependency paths <ArrowRight size={14} />
              </button>
              <p className="subtle">
                {impact.data.unaffected_completed.length} completed steps
                unaffected. {impact.data.safe_to_execute.length} independent
                steps ready.
              </p>
            </div>
          )}
          <h3>Attempt history</h3>
          {attempts.data?.map((a) => (
            <details key={a.id} className="attempt" open={a.sequence === 1}>
              <summary>
                Attempt {String(a.sequence)}{" "}
                <span className={"badge " + String(a.status)}>
                  {String(a.status)}
                </span>
              </summary>
              <p className="subtle">
                Exit {String(a.exit_code ?? "unknown")} ·{" "}
                {String(a.duration_ms ?? 0)} ms
              </p>
              <pre>
                {String(
                  a.output_summary || "Interrupted before result was recorded",
                )}
              </pre>
              {a.verification_result && (
                <pre>{pretty(String(a.verification_result))}</pre>
              )}
            </details>
          ))}
          {!!failures.data?.length && (
            <>
              <h3>Preserved failures</h3>
              {failures.data.map((f) => (
                <div key={f.id} className="failure-note">
                  <strong>{String(f.error_code)}</strong>
                  <p>{String(f.root_cause)}</p>
                  <span className="subtle">
                    {f.resolved_at
                      ? "Resolved after verification"
                      : "Unresolved"}
                  </span>
                </div>
              ))}
            </>
          )}
        </>
      )}
      {explanation.data && (
        <>
          <h3>Evidence at decision time</h3>
          <p>{String(p.evidence_status).replaceAll("_", " ")}</p>
          <button
            onClick={() =>
              onHighlight([p.id, ...explanation.data!.sources.map((s) => s.id)])
            }
          >
            <ExternalLink size={14} /> Highlight evidence path
          </button>
          {explanation.data.sources.map((s) => (
            <div className="evidence-source" key={s.id}>
              <code>BASED_ON</code>
              <p>
                {String(
                  s.summary || s.title || s.description || s.name || s.id,
                )}
              </p>
            </div>
          ))}
        </>
      )}
      {!isStep && (
        <details className="raw-details">
          <summary>Full stored properties</summary>
          <pre>{JSON.stringify(p, null, 2)}</pre>
        </details>
      )}
    </aside>
  );
}
function pretty(s: string) {
  try {
    return JSON.stringify(JSON.parse(s), null, 2);
  } catch {
    return s;
  }
}
