/** Shown when the page cannot reach a studio: ask where the backend is, then remember it.
 *
 * This is what keeps the address out of the bundle. The UI can be built once and
 * served from anywhere; the machine running the engine is named here, at runtime.
 */
import { useState } from "react";
import { apiBase, apiToken, check, setApi, setToken } from "../api";

export default function Connect({ reason, onConnected }: { reason: string; onConnected: () => void }) {
  const [url, setUrl] = useState(apiBase() || "");
  const [given, setGiven] = useState(apiToken() || "");
  const [problem, setProblem] = useState(reason);
  const [trying, setTrying] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setTrying(true);
    setProblem("");
    const failed = await check(url, given);
    setTrying(false);
    if (failed) return setProblem(failed);
    setApi(url);
    setToken(given);
    onConnected();
  }

  return (
    <div className="connect">
      <form className="connect-card panel" onSubmit={submit}>
        <p className="eyebrow">Connect to a studio</p>
        <h1 className="display">Where is the engine?</h1>
        <p className="connect-lede">
          This page is only the interface. Give it the address of the machine running
          <span className="mono"> studio.py</span>. It is remembered on this browser.
        </p>

        <label className="connect-field">
          <span className="eyebrow">Studio address</span>
          <input className="mono" value={url} onChange={(e) => setUrl(e.target.value)}
                 placeholder="http://gx10.local:8740" autoFocus spellCheck={false} />
        </label>

        <label className="connect-field">
          <span className="eyebrow">Access token</span>
          <input className="mono" type="password" value={given} onChange={(e) => setGiven(e.target.value)}
                 placeholder="AWO_TOKEN from that machine" spellCheck={false} />
        </label>

        {problem && <p className="error-note">{problem}</p>}

        <div className="connect-actions">
          <button className="btn primary" type="submit" disabled={trying || !url.trim()}>
            {trying ? "Trying…" : "Connect"}
          </button>
          <span className="mono dim">
            {apiBase() ? `last tried ${apiBase()}` : "nothing saved yet"}
          </span>
        </div>
      </form>
    </div>
  );
}
