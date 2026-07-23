import { Component } from "react";

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
    // Surface in the console for debugging; never crash the shell.
    console.error("Render error:", error, info);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="card">
        <div className="card-head"><h2>Something went wrong</h2></div>
        <div className="card-body">
          <p style={{ color: "var(--muted)", fontSize: 13.5, marginTop: 0 }}>
            This page hit an unexpected error. Your data is fine — reloading
            usually clears it. If it keeps happening, note what you clicked and
            tell your administrator.
          </p>
          <div className="row-actions">
            <button className="btn primary" onClick={() => window.location.reload()}>Reload</button>
            <button className="btn" onClick={() => { window.location.href = "/"; }}>Go to dashboard</button>
          </div>
        </div>
      </div>
    );
  }
}
