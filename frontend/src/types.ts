export type Entity = {
  id: string;
  [key: string]: string | number | boolean | undefined;
};
export type Run = Entity & {
  goal: string;
  status: string;
  created_at: number;
  mode: string;
};
export type Step = Entity & {
  title: string;
  key: string;
  status: string;
  tool_name: string;
  verification_status: string;
  run_id: string;
  attempt_count: number;
  input_json: string;
};
export type GraphNode = { id: string; label: string; properties: Entity };
export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  label: string;
};
export type Graph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
};
export type Overview = {
  runs: Record<string, number>;
  steps: Record<string, number>;
  failed_attempts: number;
  recoveries: number;
  dependency_blocked: number;
  recent_events: Entity[];
};
export type Explanation = {
  decision: Entity;
  sources: Entity[];
  paths: { source: string; relationship: string; target: string }[];
};
export type Impact = {
  directly_blocked: { step: Step; path: string[]; depth: number }[];
  transitively_affected: { step: Step; path: string[]; depth: number }[];
  unaffected_completed: Step[];
  safe_to_execute: { step: Step }[];
};
