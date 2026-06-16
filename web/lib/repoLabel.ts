/**
 * repo 値の表示整形をフロントへ移管(§2.2 決定: API は raw repo を返す)。
 * webapp/util.py:repo_label の振る舞いを 1:1 で写す。事実とその表示を分離する。
 *
 * none→no-repo / パス→basename / 登録名→そのまま / 未指定(空/null)→default。
 */
export function repoLabel(raw: string | null | undefined): string {
  const s = (raw ?? "").trim();
  if (s === "") return "default";
  if (s.toLowerCase() === "none") return "no-repo";
  if (s.includes("/")) {
    // パスの basename(末尾の / は無視)
    const parts = s.replace(/\/+$/, "").split("/");
    return parts[parts.length - 1] || s;
  }
  return s;
}
