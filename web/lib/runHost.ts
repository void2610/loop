/**
 * 現在開いている run がどの host(peer name)に属するかを子コンポーネントへ伝える Context。
 *
 * 設計: RunDetailView / RunLivePage が searchParams から ?host=<host> を読み、最上位で Provider
 * として注入する。子(EvidencePanel, TranscriptView, PhaseBreadcrumb, JudgmentForm, ArchiveRunButton)
 * は useRunHost() で host を取り、lib/fleet.ts の peerApi.*(host, ...) に渡す。
 *
 * Fleet off / 自 host の場合は undefined のままで、peerApi は同一オリジン経路に分岐(従来挙動)。
 */
import * as React from "react";

const RunHostContext = React.createContext<string | undefined>(undefined);

export const RunHostProvider = RunHostContext.Provider;

export function useRunHost(): string | undefined {
  return React.useContext(RunHostContext);
}
