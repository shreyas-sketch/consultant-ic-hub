import { Component } from "react";

function reloadedOnce() {
  try {
    if (sessionStorage.getItem("chunk-reload")) return true;
    sessionStorage.setItem("chunk-reload", "1");
    return false;
  } catch {
    return true; // storage blocked: don't risk a reload loop
  }
}

/** Catches render errors in one screen so the rest of the app keeps working.
 *  A chunk that failed to load after a deploy (old tab, new hashes) triggers one reload. */
export class ErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error) {
    const stale = /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i;
    if (stale.test(String(error?.message)) && !reloadedOnce()) {
      location.reload();
      return;
    }
    console.error(error);
  }

  componentDidUpdate(prev) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="p-6">
        <div className="rounded-xl border border-hairline bg-panel p-5">
          <p className="font-bold text-ivory">This screen hit a problem.</p>
          <p className="mt-1 text-[14px] text-ivory-70">Your data is safe. Try again, or go back to Home.</p>
          <div className="mt-4 flex gap-3">
            <button className="rounded-lg bg-gold px-4 py-2 font-bold text-bg" onClick={() => this.setState({ error: null })}>Try again</button>
            <a className="rounded-lg border border-hairline px-4 py-2 text-ivory" href="/">Home</a>
          </div>
        </div>
      </div>
    );
  }
}
