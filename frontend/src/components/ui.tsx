import type { ReactNode } from "react";
import { AlertCircle, LoaderCircle } from "lucide-react";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state-message" role="status">
      <LoaderCircle className="spin" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div className="state-message error-state" role="alert">
      <AlertCircle aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

export function StatusBadge({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "success" | "review" | "danger";
  children: ReactNode;
}) {
  return <span className={`status-badge ${tone}`}>{children}</span>;
}
