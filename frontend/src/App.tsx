import { useState } from "react";
import { Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { clearToken, getToken } from "./api/client";
import { useLive } from "./lib/ws";
import { queryInvalidator } from "./lib/liveInvalidate";
import { useQueryClient } from "@tanstack/react-query";
import Login from "./pages/Login";
import Fleet from "./pages/Fleet";
import ObserverDetail from "./pages/ObserverDetail";
import Alerts from "./pages/Alerts";
import Rules from "./pages/Rules";
import Ledger from "./pages/Ledger";
import ML from "./pages/ML";

const NAV = [
  { to: "/fleet", label: "Fleet" },
  { to: "/alerts", label: "Alerts" },
  { to: "/rules", label: "Rules" },
  { to: "/ledger", label: "Ledger" },
  { to: "/ml", label: "ML" },
];

function Shell() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [lastEvent, setLastEvent] = useState<string | null>(null);
  const connected = useLive((msg) => {
    queryInvalidator(queryClient, msg);
    if (msg.kind !== "metric") setLastEvent(msg.kind);
  });

  return (
    <div className="min-h-full flex">
      <aside
        className="w-48 shrink-0 border-r flex flex-col"
        style={{ borderColor: "var(--ring)", background: "var(--surface)" }}
      >
        <div className="px-4 py-5">
          <div className="text-lg font-semibold tracking-[0.25em]">VIGIL</div>
          <div className="text-[11px] text-muted mt-0.5">infra monitor · ledger</div>
        </div>
        <nav className="flex-1 px-2 space-y-0.5">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `block px-3 py-2 rounded text-sm ${
                  isActive ? "bg-surface-2 text-ink" : "text-ink-2 hover:text-ink"
                }`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="px-4 py-3 border-t space-y-2" style={{ borderColor: "var(--ring)" }}>
          <div className="flex items-center gap-2 text-xs">
            <span
              className={`w-2 h-2 rounded-full ${connected ? "live-dot" : ""}`}
              style={{ background: connected ? "var(--good)" : "var(--crit)" }}
            />
            <span className="text-muted">{connected ? "live stream" : "disconnected"}</span>
          </div>
          {lastEvent && <div className="text-[11px] text-muted mono truncate">last: {lastEvent}</div>}
          <button
            className="text-xs text-muted hover:text-ink"
            onClick={() => {
              clearToken();
              navigate("/login");
            }}
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 min-w-0 p-6 max-w-[1400px]">
        <Routes>
          <Route path="/fleet" element={<Fleet />} />
          <Route path="/observers/:id" element={<ObserverDetail />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/rules" element={<Rules />} />
          <Route path="/ledger" element={<Ledger />} />
          <Route path="/ml" element={<ML />} />
          <Route path="*" element={<Navigate to="/fleet" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/*" element={getToken() ? <Shell /> : <Navigate to="/login" replace />} />
    </Routes>
  );
}
