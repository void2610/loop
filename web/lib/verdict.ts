/**
 * 終了 verdict の単一定義元。status が None になったあと front-matter に確定する集合(§4)。
 * これ以前は phase-breadcrumb と ContinuePanel が同じリストを別々にハードコードしていた。
 */
export const TERMINAL_VERDICTS = [
  "pass",
  "fail",
  "handoff",
  "timeout",
  "stopped",
  "awaiting-merge",
] as const;

const TERMINAL_SET = new Set<string>(TERMINAL_VERDICTS);

/** verdict が確定値か(大文字小文字を無視)。 */
export function isTerminalVerdict(verdict: string | null | undefined): boolean {
  return !!verdict && TERMINAL_SET.has(verdict.toLowerCase());
}
