/** Hand-drawn SVG, one series each: no dual axes, recessive grid, accent trace, hover readout.
 *  Drawn in pixel space (measured, not stretched) so a dot stays round and a stroke stays 2px. */
import { useEffect, useRef, useState } from "react";

export interface Point { label: string; value: number }

function useSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    if (!ref.current) return;
    const watch = new ResizeObserver(([entry]) => {
      const box = entry.contentRect;
      setSize({ w: Math.round(box.width), h: Math.round(box.height) });
    });
    watch.observe(ref.current);
    return () => watch.disconnect();
  }, []);
  return [ref, size] as const;
}

function plot(values: number[], w: number, h: number, pad = { t: 6, r: 6, b: 6, l: 6 }) {
  const top = Math.max(...values);
  const base = Math.min(...values);
  const span = top - base || 1;
  const x = (i: number) => pad.l + (i / Math.max(1, values.length - 1)) * (w - pad.l - pad.r);
  const y = (value: number) => pad.t + (1 - (value - base) / span) * (h - pad.t - pad.b);
  return { x, y, top, base };
}

export function Spark({ points }: { points: number[] }) {
  const [ref, size] = useSize<HTMLDivElement>();
  const ready = size.w > 8 && points.length > 1;
  const { x, y } = ready ? plot(points, size.w, size.h) : { x: () => 0, y: () => 0 };
  const line = ready ? points.map((value, i) => `${x(i)},${y(value)}`).join(" ") : "";
  return (
    <div className="spark" ref={ref}>
      {points.length < 2 ? (
        <span className="spark-empty mono">one run</span>
      ) : ready && (
        <svg width={size.w} height={size.h} aria-hidden="true">
          <polygon points={`${x(0)},${size.h} ${line} ${x(points.length - 1)},${size.h}`} className="spark-area" />
          <polyline points={line} className="spark-line" />
          <circle cx={x(points.length - 1)} cy={y(points[points.length - 1])} r="2.5" className="spark-now" />
        </svg>
      )}
    </div>
  );
}

export function Bars({ points, unit = "" }: { points: Point[]; unit?: string }) {
  const [over, setOver] = useState<number | null>(null);
  if (!points.length) return <p className="empty">nothing in this range</p>;
  const top = Math.max(...points.map((p) => p.value)) || 1;
  return (
    <div className="bars">
      <div className="bars-plot">
        {points.map((point, i) => (
          <span key={point.label + i} className={`bar ${over === i ? "is-over" : ""}`}
                style={{ height: `${Math.max(2, (point.value / top) * 100)}%` }}
                onMouseEnter={() => setOver(i)} onMouseLeave={() => setOver(null)}>
            {over === i && <span className="tip mono">{point.label}: {point.value}{unit}</span>}
          </span>
        ))}
      </div>
      <div className="bars-axis mono">
        <span>{points[0]?.label}</span>
        {points.length > 1 && <span>{points[points.length - 1]?.label}</span>}
      </div>
    </div>
  );
}

export function Line({ points, unit = "", format }: {
  points: Point[]; unit?: string; format?: (value: number) => string;
}) {
  const [ref, size] = useSize<HTMLDivElement>();
  const [over, setOver] = useState<number | null>(null);
  if (points.length < 2) return <p className="empty">one point is not a trend yet</p>;
  const values = points.map((p) => p.value);
  const ready = size.w > 20;
  const pad = { t: 10, r: 10, b: 10, l: 10 };
  const { x, y, top, base } = ready ? plot(values, size.w, size.h, pad) : { x: () => 0, y: () => 0, top: 0, base: 0 };
  const line = ready ? values.map((value, i) => `${x(i)},${y(value)}`).join(" ") : "";
  const show = over == null ? points.length - 1 : over;

  return (
    <div className="linechart">
      <div className="linechart-plot" ref={ref}
           onMouseLeave={() => setOver(null)}
           onMouseMove={(event) => {
             const box = event.currentTarget.getBoundingClientRect();
             const ratio = (event.clientX - box.left - pad.l) / Math.max(1, box.width - pad.l - pad.r);
             setOver(Math.max(0, Math.min(points.length - 1, Math.round(ratio * (points.length - 1)))));
           }}>
        {ready && (
          <svg width={size.w} height={size.h} role="img" aria-label="one series over time">
            <line x1={pad.l} x2={size.w - pad.r} y1={y(base)} y2={y(base)} className="grid" />
            <line x1={pad.l} x2={size.w - pad.r} y1={y(top)} y2={y(top)} className="grid" />
            <polygon points={`${x(0)},${size.h - pad.b} ${line} ${x(points.length - 1)},${size.h - pad.b}`}
                     className="spark-area" />
            <polyline points={line} className="spark-line" />
            <line x1={x(show)} x2={x(show)} y1={pad.t} y2={size.h - pad.b} className="crosshair" />
            <circle cx={x(show)} cy={y(values[show])} r="3" className="spark-now" />
          </svg>
        )}
      </div>
      <p className="chart-foot mono">
        <span>{points[show].label}</span>
        <span>{format ? format(points[show].value) : `${points[show].value}${unit}`}</span>
      </p>
    </div>
  );
}
