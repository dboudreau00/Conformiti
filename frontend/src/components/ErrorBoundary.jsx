import { Component } from "react";
import { Button } from "./ui/Button.jsx";
import { Panel } from "./ui/Panel.jsx";

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error("Render error:", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    if (this.props.fallback !== undefined) return this.props.fallback;
    return (
      <div className="mx-auto w-full max-w-[720px] px-6 py-10">
        <Panel className="p-5">
          <h2 className="text-[17px] font-semibold tracking-[-0.015em] text-ink">Something went wrong</h2>
          <p className="mt-2 text-[13px] leading-snug text-muted">
            This page hit an unexpected error. Reload it. If it keeps happening, tell your administrator.
          </p>
          <div className="mt-4 flex gap-2">
            <Button variant="primary" onClick={() => window.location.reload()}>Reload</Button>
            <Button onClick={() => { window.location.href = "/"; }}>Go to dashboard</Button>
          </div>
        </Panel>
      </div>
    );
  }
}

export function ChromeFallback() {
  return (
    <header className="flex h-[60px] items-center justify-between gap-3 border-b border-line bg-surface px-4 text-[13px] text-muted">
      <span>The navigation could not be drawn.</span>
      <Button size="sm" onClick={() => window.location.reload()}>Reload</Button>
    </header>
  );
}
