/**
 * 判断欄のプレースホルダ = 「問い」まで(§6.7 で許可される範囲)。
 * これは生成・要約・推奨ではなく、人間に何を書くかを問うだけの固定文。
 * field の定義(key/label)は runner.JUDGMENT_FIELDS が唯一の源で、API(RunDetail.judgment_fields)経由で受け取る。
 */
export const JUDGMENT_PLACEHOLDERS: Record<string, string> = {
  notes:
    "この run をどう読んだか自由に。例: 結果を信用できるか(根拠)/ 破綻箇所・残るリスク / 次に自動検証へ入れるべきチェック / 学び。",
};
