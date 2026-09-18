import type { QueryClient } from "@tanstack/react-query";
import type { WsMessage } from "../api/types";

/** Map live bus events to react-query cache invalidations. */
export function queryInvalidator(qc: QueryClient, msg: WsMessage) {
  switch (msg.kind) {
    case "alert_fired":
    case "alert_acked":
    case "alert_resolved":
    case "alert_triaged":
      qc.invalidateQueries({ queryKey: ["alerts"] });
      break;
    case "observer_status":
      qc.invalidateQueries({ queryKey: ["observers"] });
      break;
    case "batch_anchored":
      qc.invalidateQueries({ queryKey: ["ledger"] });
      break;
  }
}
