/** The live run stream. One EventSource, reconnecting from the last sequence it saw. */
import { streamUrl } from "./api";
import { useStore } from "./store";

let source: EventSource | null = null;
let timer: number | undefined;
let attempt = 0;

export function connect(folder: string | null) {
  disconnect();
  const live = useStore.getState().run;
  const watching = live && (live.status === "running" || live.status === "paused") ? live : null;
  source = new EventSource(streamUrl(folder, watching?.seq || 0, watching?.run_id));

  source.onopen = () => {
    attempt = 0;
    useStore.getState().setConnection("open");
  };

  source.onmessage = (message) => {
    try {
      useStore.getState().applyEvent(JSON.parse(message.data));
    } catch { /* a half-written frame is not worth a crash */ }
  };

  source.onerror = () => {
    useStore.getState().setConnection("closed");
    disconnect();
    attempt += 1;
    const wait = Math.min(15000, 500 * 2 ** Math.min(attempt, 5));
    timer = window.setTimeout(() => connect(folder), wait);
  };
}

export function disconnect() {
  if (source) {
    source.close();
    source = null;
  }
  if (timer) {
    window.clearTimeout(timer);
    timer = undefined;
  }
}
