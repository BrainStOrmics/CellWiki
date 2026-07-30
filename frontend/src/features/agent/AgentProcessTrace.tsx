import { CircleAlert, CircleCheck, ChevronDown, LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { AgentProcessStep } from "../../types";

type AgentProcessTraceProps = {
  steps: AgentProcessStep[];
  live: boolean;
  title: string;
  liveLabel: string;
  completedLabel: string;
  emptyLabel: string;
};

/** Show observable Agent work without making the chat bubble depend on raw framework events. */
export function AgentProcessTrace({
  steps,
  live,
  title,
  liveLabel,
  completedLabel,
  emptyLabel,
}: AgentProcessTraceProps) {
  const [open, setOpen] = useState(live);
  const wasLive = useRef(live);

  useEffect(() => {
    if (live) setOpen(true);
    else if (wasLive.current) setOpen(false);
    wasLive.current = live;
  }, [live]);

  return (
    <details
      className={`agent-process-trace ${live ? "is-live" : "is-complete"}`}
      open={open}
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}
    >
      <summary>
        <ChevronDown size={13} />
        <span>{title}</span>
        <small>{live ? liveLabel : completedLabel}</small>
      </summary>
      <div className="agent-process-trace-list">
        {steps.length === 0 && <p className="agent-process-empty">{emptyLabel}</p>}
        {steps.map((step) => (
          <div key={step.event_id} className={`agent-process-step ${step.phase}`}>
            {step.phase === "failed" || step.phase === "cancelled"
              ? <CircleAlert size={12} />
              : step.phase === "completed"
                ? <CircleCheck size={12} />
                : <LoaderCircle size={12} className="spin" />}
            <span>{step.message || step.type.replaceAll("_", " ")}</span>
            {step.progress !== null && step.progress !== undefined && <small>{step.progress}%</small>}
          </div>
        ))}
      </div>
    </details>
  );
}
