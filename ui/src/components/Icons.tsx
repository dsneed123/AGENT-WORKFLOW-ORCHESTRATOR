/** Pure geometry, 24x24, currentColor. No emoji anywhere in this app. */
const box = {
  viewBox: "0 0 24 24", width: "1em", height: "1em", fill: "none",
  stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const, "aria-hidden": true,
};

export const Play = () => <svg {...box}><path d="M7 4l13 8-13 8V4z" fill="currentColor" stroke="none" /></svg>;
export const Pause = () => <svg {...box}><path d="M8 4v16M16 4v16" /></svg>;
export const Stop = () => <svg {...box}><rect x="5" y="5" width="14" height="14" fill="currentColor" stroke="none" /></svg>;
export const Flask = () => (
  <svg {...box}><path d="M9 3h6M10 3v6l-5 9a2 2 0 002 3h10a2 2 0 002-3l-5-9V3" /><path d="M7.5 15h9" /></svg>
);
export const Retry = () => (
  <svg {...box}><path d="M3 12a9 9 0 1015.6-6.1" /><path d="M20 3v6h-6" /></svg>
);
export const Chevron = ({ open }: { open: boolean }) => (
  <svg {...box} style={{ transform: open ? "rotate(90deg)" : "none", transition: "transform var(--duration-fast) var(--ease)" }}>
    <path d="M9 6l6 6-6 6" />
  </svg>
);
export const Sun = () => (
  <svg {...box}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19" /></svg>
);
export const Moon = () => <svg {...box}><path d="M20 13a8 8 0 11-9-9 6 6 0 009 9z" /></svg>;
export const Grid = () => (
  <svg {...box}><rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" />
    <rect x="3" y="14" width="7" height="7" /><rect x="14" y="14" width="7" height="7" /></svg>
);
export const Flow = () => (
  <svg {...box}><rect x="3" y="4" width="7" height="6" /><rect x="14" y="14" width="7" height="6" />
    <path d="M10 7h4a2 2 0 012 2v5" /></svg>
);
export const Fit = () => (
  <svg {...box}><path d="M4 9V4h5M20 15v5h-5M20 9V4h-5M4 15v5h5" /></svg>
);
export const Plus = () => <svg {...box}><path d="M12 5v14M5 12h14" /></svg>;
export const Minus = () => <svg {...box}><path d="M5 12h14" /></svg>;
export const Pin = () => (
  <svg {...box}><path d="M12 17v5" /><path d="M7 12V4h10v8l3 3H4l3-3z" /></svg>
);
export const Collapse = ({ side }: { side: "left" | "right" }) => (
  <svg {...box}><path d={side === "left" ? "M15 6l-6 6 6 6" : "M9 6l6 6-6 6"} /></svg>
);
