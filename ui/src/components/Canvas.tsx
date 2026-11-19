import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Handle, MiniMap, Position, ReactFlow, ReactFlowProvider, useReactFlow,
  type Edge, type Node, type NodeProps,
} from "@xyflow/react";
import { useShallow } from "zustand/react/shallow";
import "@xyflow/react/dist/style.css";
import { Fit, Minus, Plus } from "./Icons";
import { nodesOf } from "./Inspector";
import { diffStatus, useStore } from "../store";
import type { FlowNode, NodeState } from "../types";

const STEP_X = 260;

type CardData = {
  node: NodeState;
  config: FlowNode | undefined;
  selected: boolean;
  change?: "added" | "removed" | "modified";
};

function Card({ data }: NodeProps<Node<CardData>>) {
  const { node, config, selected, change } = data;
  const select = useStore((s) => s.select);
  return (
    <div
      className={`gnode is-${node.type} s-${node.status} ${selected ? "is-sel" : ""} ${node.disabled ? "is-off" : ""} ${change ? `d-${change}` : ""}`}
      onClick={() => select(node.name)}
    >
      <Handle type="target" position={Position.Left} />
      <div className="gnode-head">
        <span className="gnode-kind mono">{node.type}</span>
        {node.status === "running" && <span className="spinner" aria-label="running" />}
        {node.status === "failed" && <span className="badge is-err mono">error</span>}
        {change && <span className={`badge is-${change} mono`}>{change}</span>}
      </div>
      <p className="gnode-name">{node.name}</p>
      <p className="gnode-foot mono">
        {config?.model || config?.sink || config?.source || node.mode}
        {node.ms != null ? ` · ${node.ms}ms` : ""}
      </p>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const TYPES = { card: Card };

function Inner() {
  const { run, records, flows, folder, selected, source, proposal } = useStore(useShallow((s) => ({
    run: s.run, records: s.records, flows: s.flows, folder: s.folder, selected: s.selected,
    source: s.canvasSource, proposal: s.proposal,
  })));
  const select = useStore((s) => s.select);
  const setSource = useStore((s) => s.setCanvasSource);
  const nodeAction = useStore((s) => s.nodeAction);
  const { fitView, zoomIn, zoomOut } = useReactFlow();
  const [menu, setMenu] = useState<{ x: number; y: number; name: string } | null>(null);
  const [config, setConfig] = useState<FlowNode | null>(null);
  const fitted = useRef<string | null>(null);

  const flow = flows.find((f) => f.folder === folder);
  const live = source === "live" ? run : null;
  const states = useMemo(
    () => nodesOf(source === "live" ? run : null, source === "live" ? records : records, flow),
    [run, records, flow, source]);

  const nodes: Node<CardData>[] = useMemo(() => states.map((node, i) => {
    const conf = flow?.nodes.find((n) => n.name === node.name);
    const layout = conf?.layout;
    return {
      id: node.name,
      type: "card",
      position: layout ? { x: layout.x, y: layout.y } : { x: i * STEP_X, y: (i % 2) * 12 },
      data: { node, config: conf, selected: selected === node.name,
              change: diffStatus(proposal?.diff, node.name) },
      width: 190,
      height: 86,
      draggable: true,
    };
  }), [states, flow, selected, proposal]);

  const edges: Edge[] = useMemo(() => states.slice(1).map((node, i) => {
    const from = states[i];
    const flowing = live && (node.status === "running" || from.status === "running");
    const size = from.output ? `${(from.output.length / 1024).toFixed(1)} kB` : "";
    return {
      id: `${from.name}->${node.name}`,
      source: from.name,
      target: node.name,
      animated: Boolean(flowing),
      label: size,
      className: flowing ? "is-flowing" : undefined,
    };
  }), [states, live]);

  useEffect(() => {
    if (fitted.current === folder || !nodes.length) return;
    fitted.current = folder;
    window.setTimeout(() => fitView({ padding: 0.2, duration: 160 }), 60);
  }, [folder, nodes.length, fitView]);

  const onContext = useCallback((event: React.MouseEvent, node: Node) => {
    event.preventDefault();
    setMenu({ x: event.clientX, y: event.clientY, name: node.id });
  }, []);

  if (!flow) return <section className="panel"><p className="empty">pick a workflow to see its graph</p></section>;
  if (!states.length) return <section className="panel"><p className="empty">this workflow has no nodes</p></section>;

  return (
    <section className="panel canvas" onClick={() => setMenu(null)}>
      <div className="panel-head">
        <p className="eyebrow">Graph</p>
        <span className="mono dim">{states.length} nodes</span>
        <div className="canvas-tools">
          <div className="toggle">
            <button className={`chip ${source === "live" ? "is-on" : ""}`} onClick={() => setSource("live")}>live</button>
            <button className={`chip ${source === "last" ? "is-on" : ""}`} onClick={() => setSource("last")}>last run</button>
          </div>
          <button className="btn ghost icon" title="Zoom in" onClick={() => zoomIn()}><Plus /></button>
          <button className="btn ghost icon" title="Zoom out" onClick={() => zoomOut()}><Minus /></button>
          <button className="btn ghost icon" title="Fit to view" onClick={() => fitView({ padding: 0.2 })}><Fit /></button>
        </div>
      </div>

      <div className="panel-body flowpane">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={TYPES}
          onNodeClick={(_, node) => select(node.id)}
          onNodeContextMenu={onContext}
          onNodeDragStop={(_, node) => void nodeAction("move", node.id, node.position)}
          proOptions={{ hideAttribution: true }}
          minZoom={0.3}
          maxZoom={1.75}
          fitView
        >
          <MiniMap pannable zoomable className="minimap" nodeStrokeWidth={2}
                   nodeColor="var(--accent)" maskColor="var(--scrim)" />
        </ReactFlow>

        {menu && (
          <ul className="menu" style={{ left: menu.x, top: menu.y }} onClick={(e) => e.stopPropagation()}>
            <li><button onClick={() => { void nodeAction("disable", menu.name); setMenu(null); }}>
              {flow.nodes.find((n) => n.name === menu.name)?.disabled ? "Enable node" : "Disable node"}</button></li>
            <li><button onClick={() => { void nodeAction("duplicate", menu.name); setMenu(null); }}>Duplicate</button></li>
            <li><button className="is-danger" onClick={() => { void nodeAction("delete", menu.name); setMenu(null); }}>Delete</button></li>
            <li><button onClick={() => { setConfig(flow.nodes.find((n) => n.name === menu.name) || null); setMenu(null); }}>
              View config</button></li>
          </ul>
        )}

        {config && (
          <div className="sheet" onClick={() => setConfig(null)}>
            <div className="sheet-body" onClick={(e) => e.stopPropagation()}>
              <div className="panel-head">
                <p className="eyebrow">Config · {config.name}</p>
                <button className="btn ghost small" onClick={() => setConfig(null)}>close</button>
              </div>
              <pre className="transcript">{JSON.stringify(config, null, 2)}</pre>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

export default function Canvas() {
  return <ReactFlowProvider><Inner /></ReactFlowProvider>;
}
