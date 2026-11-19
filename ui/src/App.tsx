import { useEffect, useState } from "react";
import ControlBar from "./components/ControlBar";
import Inspector from "./components/Inspector";
import Canvas from "./components/Canvas";
import Chat from "./components/Chat";
import Dashboards from "./components/Dashboards";
import { Collapse, Flow, Grid, Moon, Sun } from "./components/Icons";
import { useShallow } from "zustand/react/shallow";
import { useStore } from "./store";
import { connect, disconnect } from "./stream";

type Route = "workspace" | "dashboards";

const routeOf = (path: string): Route => (path.startsWith("/dashboards") ? "dashboards" : "workspace");

function Resizer({ side }: { side: "left" | "right" }) {
  const setPanelWidth = useStore((s) => s.setPanelWidth);
  return (
    <div
      className={`resizer resizer-${side}`}
      role="separator"
      aria-orientation="vertical"
      onMouseDown={(down) => {
        down.preventDefault();
        const startX = down.clientX;
        const start = useStore.getState().panels[side === "left" ? "leftWidth" : "rightWidth"];
        const move = (e: MouseEvent) =>
          setPanelWidth(side, side === "left" ? start + (e.clientX - startX) : start - (e.clientX - startX));
        const up = () => {
          window.removeEventListener("mousemove", move);
          window.removeEventListener("mouseup", up);
        };
        window.addEventListener("mousemove", move);
        window.addEventListener("mouseup", up);
      }}
    />
  );
}

export default function App() {
  const [route, setRoute] = useState<Route>(routeOf(location.pathname));
  const [narrow, setNarrow] = useState(window.innerWidth < 1200);
  const { folder, panels, theme, run } = useStore(useShallow((s) => ({
    folder: s.folder, panels: s.panels, theme: s.theme, run: s.run,
  })));
  const load = useStore((s) => s.load);
  const setTheme = useStore((s) => s.setTheme);
  const togglePanel = useStore((s) => s.togglePanel);
  const loadDash = useStore((s) => s.loadDash);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    const onPop = () => setRoute(routeOf(location.pathname));
    const onSize = () => setNarrow(window.innerWidth < 1200);
    window.addEventListener("popstate", onPop);
    window.addEventListener("resize", onSize);
    return () => {
      window.removeEventListener("popstate", onPop);
      window.removeEventListener("resize", onSize);
    };
  }, []);

  useEffect(() => {
    if (!folder) return;
    connect(folder);
    return () => disconnect();
  }, [folder]);

  useEffect(() => {
    if (route === "dashboards") void loadDash();
  }, [route, loadDash]);

  const go = (next: Route) => {
    history.pushState({}, "", next === "dashboards" ? "/dashboards" : "/");
    setRoute(next);
  };

  const busy = run?.status === "running" || run?.status === "paused";

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes((e.target as HTMLElement)?.tagName);
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      const state = useStore.getState();
      if (e.code === "Space") {
        e.preventDefault();
        if (!busy) void state.start("run");
        else void state.control(state.run?.status === "paused" ? "resume" : "pause");
      } else if (e.key === "Escape" && busy) {
        void state.control("stop");
      } else if (e.key.toLowerCase() === "t" && !busy) {
        void state.start("test");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy]);

  return (
    <div className="app">
      <header className="topbar">
        <span className="wordmark">
          <span className="wordmark-sq" />
          <span className="display">AWO&nbsp;Studio</span>
        </span>
        <nav className="routes">
          <button className={`tab ${route === "workspace" ? "is-on" : ""}`} onClick={() => go("workspace")}>
            <Flow /> Workspace
          </button>
          <button className={`tab ${route === "dashboards" ? "is-on" : ""}`} onClick={() => go("dashboards")}>
            <Grid /> Dashboards
          </button>
        </nav>
        <span className="topbar-right">
          {route === "workspace" && (
            <>
              <button className="btn ghost icon" title="Node inspector" aria-pressed={panels.left}
                      onClick={() => togglePanel("left")}><Collapse side="left" /></button>
              <button className="btn ghost icon" title="Workflow chat" aria-pressed={panels.right}
                      onClick={() => togglePanel("right")}><Collapse side="right" /></button>
            </>
          )}
          <button className="btn ghost icon" title="Light or dark"
                  onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? <Sun /> : <Moon />}
          </button>
        </span>
      </header>

      {route === "dashboards" ? (
        <Dashboards />
      ) : (
        <>
          <ControlBar />
          <main className={`shell ${narrow ? "is-narrow" : ""}`}
                style={{
                  gridTemplateColumns: narrow
                    ? "minmax(0,1fr)"
                    : `${panels.left ? panels.leftWidth : 0}px minmax(0,1fr) ${panels.right ? panels.rightWidth : 0}px`,
                }}>
            {panels.left && (
              <div className="col col-left">
                <Inspector />
                {!narrow && <Resizer side="left" />}
              </div>
            )}
            <div className="col col-center"><Canvas /></div>
            {panels.right && (
              <div className="col col-right">
                {!narrow && <Resizer side="right" />}
                <Chat />
              </div>
            )}
          </main>
        </>
      )}
    </div>
  );
}
