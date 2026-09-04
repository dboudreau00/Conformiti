import { Component } from "react";
import { Button } from "./ui/Button.jsx";
import { Panel } from "./ui/Panel.jsx";

/**
 * Catches render errors below it and shows a recoverable card instead of a
 * white screen. State-corruption from one page can't take down the shell.
 */
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
    return (
      <div className="mx-auto w-full max-w-[720px] px-6 py-10">
        <Panel className="p-5">
          <h2 className="text-[17px] font-semibold tracking-[-0.015em] text-ink">Something went wrong</h2>
          <p className="mt-2 text-[13px] leading-snug text-muted">
            This page hit an unexpected error. Your data is fine — reloading usually clears it. If it keeps happening, note what you clicked and tell your administrator.
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
