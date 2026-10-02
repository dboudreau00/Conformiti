import { Component } from "react";
import { Button } from "./ui/Button.jsx";
import { Panel } from "./ui/Panel.jsx";

/**
 * Catches render errors below it and shows a recoverable card instead of a
 * white screen. State-corruption from one page can't take down the shell.
 * The bar and the side menu use it too, with a `fallback` of their own, so
 * a crash in the chrome costs that piece and not the page under it.
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
    if (this.props.fallback !== undefined) return this.props.fallback;
    return (
      <div className="mx-auto w-full max-w-[720px] px-6 py-10">
        <Panel className="p-5">
          <h2 className="text-[17px] font-semibold tracking-[-0.015em] text-ink">Something went wrong</h2>
          <p className="mt-2 text-[13px] leading-snug text-muted">
            This page hit an unexpected error. Your data is fine, reloading usually clears it. If it keeps happening, note what you clicked and tell your administrator.
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

/** What the top bar shows if it cannot be drawn: the way out and nothing else. */
export function ChromeFallback() {
  return (
    <header className="flex h-[60px] items-center justify-between gap-3 border-b border-line bg-surface px-4 text-[13px] text-muted">
      <span>The navigation could not be drawn.</span>
      <Button size="sm" onClick={() => window.location.reload()}>Reload</Button>
    </header>
  );
}
