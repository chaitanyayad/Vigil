import { useEffect, useRef, useState } from "react";
import { getToken } from "../api/client";
import type { WsMessage } from "../api/types";

/** Live event stream from /v1/ws/live with auto-reconnect. */
export function useLive(onMessage: (msg: WsMessage) => void) {
  const [connected, setConnected] = useState(false);
  const handler = useRef(onMessage);
  handler.current = onMessage;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 1000;

    const connect = () => {
      const token = getToken();
      if (!token) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/v1/ws/live?token=${token}`);
      ws.onopen = () => {
        setConnected(true);
        retry = 1000;
      };
      ws.onmessage = (ev) => {
        try {
          handler.current(JSON.parse(ev.data));
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) {
          retry = Math.min(retry * 2, 15000);
          setTimeout(connect, retry);
        }
      };
    };
    connect();
    const ping = setInterval(() => ws?.readyState === 1 && ws.send("ping"), 25000);
    return () => {
      closed = true;
      clearInterval(ping);
      ws?.close();
    };
  }, []);

  return connected;
}

export function fmtBps(v: number | null | undefined): string {
  if (v == null) return "–";
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)} Gb/s`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)} Mb/s`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)} kb/s`;
  return `${Math.round(v)} b/s`;
}

export function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 5) return "just now";
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function shortHash(h: string | null, n = 10): string {
  if (!h) return "–";
  return h.length > n + 2 ? `${h.slice(0, n)}…` : h;
}
