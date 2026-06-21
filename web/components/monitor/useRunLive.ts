"use client";

import * as React from "react";

import { subscribeRun, type RunStreamEventData } from "@/lib/sse";

export const ROLES = [
  { key: "implementer", label: "Implementer" },
  { key: "verifier", label: "Verifier" },
] as const;

export type RoleKey = (typeof ROLES)[number]["key"];

const ROLE_KEYS = new Set<string>(ROLES.map((r) => r.key));

function roleOf(ev: RunStreamEventData): RoleKey {
  // role 欠落イベントは implementer 扱い(本体出力の既定)。事実の振り分けのみ。
  const r = typeof ev.role === "string" ? ev.role : "";
  return (ROLE_KEYS.has(r) ? r : "implementer") as RoleKey;
}

export type RunLiveState = {
  byRole: Record<RoleKey, RunStreamEventData[]>;
  phase: string | null;
  ended: boolean;
  connected: boolean;
};

const EMPTY_BY_ROLE = (): Record<RoleKey, RunStreamEventData[]> => ({
  implementer: [],
  verifier: [],
});

/**
 * 進行中/完了済み run のライブ transcript を購読する(§3.3: 完了 run は即時フル再生→end)。
 * 凍結された sse.ts の subscribeRun を import するだけ。再接続は EventSource 標準に委ねる。
 * token は WS6 で実体化する短命 signed query token(現状 undefined)。
 * Fleet: peerBase に他 host の Next フロント URL を渡すと、その host の backend(:8765 置換)を購読。
 */
export function useRunLive(runId: string, token?: string, peerBase?: string): RunLiveState {
  const [byRole, setByRole] = React.useState<Record<RoleKey, RunStreamEventData[]>>(
    EMPTY_BY_ROLE
  );
  const [phase, setPhase] = React.useState<string | null>(null);
  const [ended, setEnded] = React.useState(false);
  const [connected, setConnected] = React.useState(false);

  React.useEffect(() => {
    setByRole(EMPTY_BY_ROLE());
    setPhase(null);
    setEnded(false);
    setConnected(true);

    const close = subscribeRun(
      runId,
      {
        event: (d) => {
          const role = roleOf(d);
          setByRole((prev) => ({ ...prev, [role]: [...prev[role], d] }));
        },
        phase: (d) => setPhase(d.phase),
        end: () => {
          setEnded(true);
          setConnected(false);
        },
        error: (e) => {
          setConnected(false);
          // sse.ts の error 多発しきい値で fatal=true が付与される。reload を促す UI のため ended にする。
          if ((e as Event & { fatal?: boolean }).fatal) setEnded(true);
        },
      },
      token,
      peerBase,
    );
    return () => {
      close();
      setConnected(false);
    };
  }, [runId, token, peerBase]);

  return { byRole, phase, ended, connected };
}
