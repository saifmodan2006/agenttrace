import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Workflow, X, ShieldCheck, ArrowRight } from "lucide-react";
import { api } from "../api";
import type { Run } from "../types";

export default function CreateRun({
  onClose,
  onCreated,
  configured,
}: {
  onClose: () => void;
  onCreated: (id: string) => void;
  configured: boolean;
}) {
  const [goal, setGoal] = useState(
    "Repair and validate the broken calculator application",
  );
  const [description, setDescription] = useState("");
  const [mode, setMode] = useState("demo");
  const create = useMutation({
    mutationFn: async () => {
      const run = await api<Run>("/runs", {
        goal,
        description,
        mode,
        scenario: "broken-app",
      });
      await api("/runs/" + run.id + "/start", {});
      return run;
    },
    onSuccess: (r) => onCreated(r.id),
  });
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const items = Array.from(
          document.querySelectorAll<HTMLElement>(
            ".modal button:not(:disabled), .modal input, .modal textarea, .modal select",
          ),
        );
        const first = items[0],
          last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => {
      document.removeEventListener("keydown", handler);
      previous?.focus();
    };
  }, [onClose]);
  return (
    <div className="modal-backdrop">
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-title"
      >
        <div className="panel-heading">
          <span className="modal-icon">
            <Workflow size={23} />
          </span>
          <button
            className="icon-button"
            aria-label="Close new run"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>
        <h2 id="create-title">Give your agents a goal.</h2>
        <p>
          A persistent plan, a shared memory, and evidence for every action.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <label htmlFor="goal">Execution goal</label>
          <textarea
            id="goal"
            autoFocus
            required
            minLength={3}
            maxLength={2000}
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
          />
          <label htmlFor="description">
            Additional context <span className="subtle">(optional)</span>
          </label>
          <input
            id="description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            maxLength={4000}
          />
          <label htmlFor="scenario">Workspace scenario</label>
          <select id="scenario">
            <option>Broken application: diagnosis & recovery</option>
          </select>
          <label htmlFor="mode">Planning mode</label>
          <select
            id="mode"
            value={mode}
            onChange={(e) => setMode(e.target.value)}
          >
            <option value="demo">Deterministic demonstration</option>
            <option value="llm" disabled={!configured}>
              Live OpenAI-compatible planner
              {!configured ? " — not configured" : ""}
            </option>
          </select>
          <div className="notice">
            <ShieldCheck size={17} />
            <span>
              Runs real allowlisted tools in an isolated local workspace.
              Deterministic mode uses a fixed plan and approved repair.
            </span>
          </div>
          {create.error && (
            <p role="alert" className="error-text">
              {create.error.message}
            </p>
          )}
          <div className="modal-actions">
            <button type="button" onClick={onClose}>
              Cancel
            </button>
            <button
              className="primary"
              type="submit"
              disabled={create.isPending}
            >
              {create.isPending ? "Creating graph…" : "Create & start run"}
              <ArrowRight size={16} />
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
