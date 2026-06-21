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

/**
 * ?host=<host> を付ける(host 空 / undefined なら付けない)。
 * self に host を付けるか否か(merge view は付け、自 host 詳細は付けない)をここ 1 箇所で決め、
 * 各所に散っていた `host ? \`?host=...\` : ""` の手書きと付与漏れを無くす。
 */
export function hostQuery(host?: string): string {
  return host ? `?host=${encodeURIComponent(host)}` : "";
}

/** run 詳細 / live / transcript への href。host 付与は hostQuery に集約。 */
export function runHref(runId: string, host?: string, sub?: "live" | "transcript"): string {
  return `/runs/${encodeURIComponent(runId)}${sub ? `/${sub}` : ""}${hostQuery(host)}`;
}

/** task 詳細への href。 */
export function taskHref(taskId: string, host?: string): string {
  return `/tasks/${encodeURIComponent(taskId)}${hostQuery(host)}`;
}
