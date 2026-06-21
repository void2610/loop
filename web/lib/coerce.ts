/**
 * unknown スカラの表示用強制。API は事実を素で返し、文字列化・数値化はフロントの責務(§2.2)。
 * これ以前は asString / fmString / asNumber が複数コンポーネントに個別実装されていた。
 */

/** 値が文字列ならそれを、でなければ undefined。 */
export function asString(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

/** asString のフォールバック付き(既定は空文字)。 */
export function asStringOr(v: unknown, fallback = ""): string {
  return asString(v) ?? fallback;
}

/** どんな値も表示用文字列へ(null/undefined→"", string→そのまま, それ以外→String())。 */
export function stringify(v: unknown): string {
  if (v === null || v === undefined) return "";
  return typeof v === "string" ? v : String(v);
}

/** 有限数ならそれを、でなければ null(数値以外は空表示にして事実を歪めない)。 */
export function asFiniteNumber(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}
