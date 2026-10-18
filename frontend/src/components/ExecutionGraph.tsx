import { useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  MarkerType,
} from "@xyflow/react";
import type { NodeProps, Node, Edge } from "@xyflow/react";
import {
  GitBranch,
  CheckCircle2,
  AlertCircle,
  Box,
  Bot,
  FileCheck2,
  Network,
} from "lucide-react";
import type { Graph, GraphNode } from "../types";

type TraceNode = Node<{ entity: GraphNode; highlight: boolean }, "trace">;
function TraceCard({ data }: NodeProps<TraceNode>) {
  const { entity, highlight } = data;
  const p = entity.properties;
  const Icon =
    entity.label === "Step"
      ? p.status === "succeeded"
        ? CheckCircle2
        : GitBranch
      : entity.label === "Failure"
        ? AlertCircle
        : entity.label === "AgentRun"
          ? Network
          : entity.label === "Agent"
            ? Bot
            : entity.label === "Artifact"
              ? FileCheck2
              : Box;
  return (
    <div
      className={
        "trace-node " +
        (highlight ? "highlight " : "") +
        (p.status || entity.label).toString()
      }
    >
      <Handle type="target" position={Position.Left} />
      <div className="node-top">
        <Icon size={15} />
        <span>
          {entity.label === "AgentRun"
            ? "EXECUTION GOAL"
            : entity.label.toUpperCase()}
        </span>
        <span className="node-dot" />
      </div>
      <strong>
        {String(
          p.title ||
            p.name ||
            p.goal ||
            p.action ||
            p.error_code ||
            p.filename ||
            entity.label,
        )}
      </strong>
      <div className="node-bottom">
        <span>
          {String(p.tool_name || p.decision_type || p.type || "graph record")}
        </span>
        <span>
          {String(p.status || p.evidence_status || "recorded").replaceAll(
            "_",
            " ",
          )}
        </span>
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { trace: TraceCard };

export default function ExecutionGraph({
  graph,
  onSelect,
  highlight = [],
}: {
  graph: Graph;
  onSelect: (n: GraphNode) => void;
  highlight?: string[];
}) {
  const [expanded, setExpanded] = useState(false);
  const [status, setStatus] = useState("all");
  const [agent, setAgent] = useState("all");
  const [dependencies, setDependencies] = useState(false);
  const [fitKey, setFitKey] = useState(0);
  const { nodes, edges } = useMemo(() => {
    const visible = graph.nodes
      .filter(
        (n) =>
          expanded ||
          ["AgentRun", "Step", "Failure", "Procedure", "Artifact"].includes(
            n.label,
          ),
      )
      .filter(
        (n) =>
          n.label !== "Step" ||
          status === "all" ||
          n.properties.status === status,
      )
      .filter(
        (n) =>
          n.label !== "Step" ||
          agent === "all" ||
          n.properties.lease_owner === agent,
      );
    const ids = new Set(visible.map((n) => n.id));
    const depths = new Map<string, number>();
    function depth(id: string, stack = new Set<string>()): number {
      if (depths.has(id)) return depths.get(id)!;
      if (stack.has(id)) return 0;
      const next = new Set(stack);
      next.add(id);
      const ds = graph.edges
        .filter((e) => e.source === id && e.label === "DEPENDS_ON")
        .map((e) => depth(e.target, next) + 1);
      const d = ds.length ? Math.max(...ds) : 0;
      depths.set(id, d);
      return d;
    }
    const lanes = new Map<number, number>();
    const positions = new Map<string, { x: number; y: number }>();
    const steps = visible
      .filter((n) => n.label === "Step")
      .sort(
        (a, b) =>
          Number(a.properties.created_at) - Number(b.properties.created_at),
      );
    for (const n of steps) {
      const d = depth(n.id);
      const lane = lanes.get(d) || 0;
      lanes.set(d, lane + 1);
      positions.set(n.id, { x: 80 + d * 320, y: 200 + lane * 175 });
    }
    const maxDepth = Math.max(0, ...depths.values());
    let extra = 0;
    for (const n of visible) {
      if (n.label === "AgentRun") positions.set(n.id, { x: 80, y: 20 });
      else if (n.label !== "Step") {
        positions.set(n.id, {
          x: 80 + (extra % Math.max(maxDepth + 1, 2)) * 320,
          y: 610 + Math.floor(extra / Math.max(maxDepth + 1, 2)) * 160,
        });
        extra++;
      }
    }
    const nodes: TraceNode[] = visible.map((n) => ({
      id: n.id,
      type: "trace",
      position: positions.get(n.id)!,
      data: { entity: n, highlight: highlight.includes(n.id) },
      ariaLabel:
        n.label +
        ": " +
        String(
          n.properties.title || n.properties.goal || n.properties.name || n.id,
        ),
    }));
    const edges: Edge[] = graph.edges
      .filter((e) => ids.has(e.source) && ids.has(e.target))
      .map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        type: "smoothstep",
        animated: false,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 15,
          height: 15,
          color:
            highlight.includes(e.source) && highlight.includes(e.target)
              ? "#65dfc2"
              : "#667184",
        },
        style: {
          stroke:
            highlight.includes(e.source) && highlight.includes(e.target)
              ? "#65dfc2"
              : dependencies && e.label === "DEPENDS_ON"
                ? "#65dfc2"
                : "#4d586b",
          strokeWidth:
            highlight.includes(e.source) && highlight.includes(e.target)
              ? 2.5
              : 1.3,
        },
        labelStyle: { fill: "#a8b2c2", fontSize: 9, fontFamily: "monospace" },
        labelBgStyle: { fill: "#11161f" },
        labelBgPadding: [5, 3] as [number, number],
      }));
    return { nodes, edges };
  }, [graph, expanded, status, agent, highlight, dependencies]);
  const owners = [
    ...new Set(
      graph.nodes
        .filter((n) => n.label === "Step" && n.properties.lease_owner)
        .map((n) => String(n.properties.lease_owner)),
    ),
  ];
  return (
    <section className="graph-shell">
      <div className="graph-toolbar">
        <div className="toolbar-left">
          <span className="eyebrow">PERSISTED EXECUTION GRAPH</span>
          <span className="subtle">
            {nodes.length} nodes · {edges.length} relationships
          </span>
        </div>
        <div className="toolbar-actions">
          <select
            aria-label="Filter graph by status"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="all">All statuses</option>
            {[
              "pending",
              "running",
              "verifying",
              "succeeded",
              "retryable",
              "failed",
              "needs_reconciliation",
            ].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <select
            aria-label="Filter graph by agent"
            value={agent}
            onChange={(e) => setAgent(e.target.value)}
          >
            <option value="all">All agents</option>
            {owners.map((o) => (
              <option key={o}>{o}</option>
            ))}
          </select>
          <button
            className={dependencies ? "active" : ""}
            onClick={() => setDependencies(!dependencies)}
          >
            Dependencies
          </button>
          <button onClick={() => setExpanded(!expanded)}>
            {expanded ? "Core graph" : "Expand evidence"}
          </button>
          <button onClick={() => setFitKey((k) => k + 1)}>Fit graph</button>
        </div>
      </div>
      <div className="graph-canvas" data-testid="execution-graph">
        <ReactFlow
          key={fitKey}
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeClick={(_, n) => onSelect(n.data.entity as GraphNode)}
          fitView
          fitViewOptions={{ padding: 0.18, maxZoom: 0.95 }}
          minZoom={0.2}
          maxZoom={1.8}
          colorMode="dark"
          nodesDraggable={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={22} size={1} color="#303948" />
          <Controls showInteractive={false} />
          <MiniMap
            nodeColor={(n) =>
              n.data?.entity &&
              (n.data.entity as GraphNode).properties.status === "succeeded"
                ? "#62cfb3"
                : "#64748b"
            }
            maskColor="rgba(11,14,20,.8)"
          />
        </ReactFlow>
      </div>
      <div className="graph-legend">
        <span>
          <i className="dot teal" />
          Verified
        </span>
        <span>
          <i className="dot blue" />
          Running
        </span>
        <span>
          <i className="dot amber" />
          Recovery / retry
        </span>
        <span>
          <i className="dot muted" />
          Pending
        </span>
        <span className="legend-note">
          DEPENDS_ON points toward the prerequisite
        </span>
      </div>
      {graph.truncated && (
        <p className="notice">
          Graph limit reached. Use the API to inspect additional records.
        </p>
      )}
    </section>
  );
}
