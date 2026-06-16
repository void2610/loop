/**
 * 各判断フィールドのプレースホルダ = 「問い」まで(§6.7 で許可される範囲)。
 * これは生成・要約・推奨ではなく、人間に何を書くかを問うだけの固定文。
 * field の定義そのもの(key/label/順序)は runner.JUDGMENT_FIELDS が唯一の源で、
 * API(RunDetail.judgment_fields)経由で受け取る。ここは問いの静的辞書に留める。
 */
export const JUDGMENT_PLACEHOLDERS: Record<string, string> = {
  trust: "この run の結果を信用できるか?(根拠とともに)",
  risk: "破綻箇所・失敗・残るリスクは?",
  checks: "次に自動検証へ入れるべきチェックは?(review-notes.md に追記される)",
  learning: "この run から得た学びは?",
};
