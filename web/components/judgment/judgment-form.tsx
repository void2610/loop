"use client";

import { useCallback, useImperativeHandle, useRef, useState, forwardRef } from "react";
import { SquarePen } from "lucide-react";

import { api, ApiError, type JudgmentInput } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import { JUDGMENT_PLACEHOLDERS } from "./placeholders";

// 判断フォームの prefill 値。key→値(改行保持)。parse_judgment が返した「人間が過去に書いた値」のみ。
export type JudgmentValues = Record<string, string>;

export type JudgmentFormHandle = { save: () => void };

// 人間が選べる verdict(覆し用)。空 = 覆さない。runner の判定は別物(参照のみ)。
const HUMAN_VERDICTS = ["pass", "fail", "revise", "handoff"] as const;

type Props = {
  runId: string;
  // [key, label]。runner.JUDGMENT_FIELDS が唯一の源(RunDetail.judgment_fields)。
  fields: string[][];
  values: JudgmentValues;
  reviewed: boolean;
  // runner の判定(参照表示のみ。select の初期値には流し込まない=自動入力しない)。
  verdict: string;
  // 人間が過去に覆した判定(prefill)。空=未覆し。
  humanVerdict: string;
  // 保存成功後に親へ通知(次 run 遷移の導線は親が持つ)。
  onSaved?: () => void;
};

// 判断(種類B)フォーム。prefill のみ・生成ゼロ。
// 禁止(§6.7): オートサジェスト/補完/履歴、要約・下書き生成、テンプレ補完、推奨表示、必須化誘導、LLM 呼び出し。
// Verifier/Implementer の出力を value/defaultValue に流し込まない。runner.write_judgment が唯一の保存通路。
export const JudgmentForm = forwardRef<JudgmentFormHandle, Props>(function JudgmentForm(
  { runId, fields, values, reviewed, verdict, humanVerdict, onSaved },
  ref,
) {
  // 制御値。初期値は prefill(人間が過去に書いた値)のみ。verdict 等は一切反映しない。
  const initial: JudgmentValues = {};
  for (const [key] of fields) initial[key] = values[key] ?? "";
  const [state, setState] = useState<JudgmentValues>(initial);
  // 覆し判定。初期値は人間が過去に覆した値のみ(runner の verdict は入れない=自動入力しない)。
  const [human, setHuman] = useState<string>(humanVerdict ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedReviewed, setSavedReviewed] = useState(reviewed);
  const formRef = useRef<HTMLFormElement>(null);

  const save = useCallback(async () => {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      // JudgmentInput の 4 キーのみを無加工で送る。改行は透過し strip は runner に委ねる(§6.6)。
      const body: JudgmentInput = {
        trust: state.trust ?? "",
        risk: state.risk ?? "",
        checks: state.checks ?? "",
        learning: state.learning ?? "",
        human_verdict: human,
      };
      await api.putJudgment(runId, body);
      setSavedReviewed(true);
      onSaved?.();
    } catch (e) {
      // 失敗時も入力テキストは保持する(§6.5 / §6.9: テキストを失わせない)。
      setError(e instanceof ApiError ? e.message : "保存に失敗しました。再試行してください");
    } finally {
      setSaving(false);
    }
  }, [saving, state, human, runId, onSaved]);

  useImperativeHandle(ref, () => ({ save }), [save]);

  // ⌘↵ / Ctrl+↵ で保存。テキストエリア内でも有効(§6.5)。
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        void save();
      }
    },
    [save],
  );

  return (
    <form
      ref={formRef}
      onKeyDown={onKeyDown}
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      className="surface flex h-full flex-col gap-3 p-4"
    >
      <div className="flex items-start justify-between gap-2 border-b border-border/60 pb-3">
        <div className="flex items-center gap-2">
          <SquarePen className="size-4 text-primary" aria-hidden />
          <h3 className="text-sm font-semibold">判断</h3>
          <span className="text-xs text-muted-foreground">
            種類B / あなたが書く・GUI は生成しない
          </span>
        </div>
        {savedReviewed ? (
          <Badge variant="pass" title="再保存すると判断を全置換します">reviewed ✓</Badge>
        ) : (
          <Badge variant="outline" className="text-muted-foreground">未レビュー</Badge>
        )}
      </div>

      <div className="flex items-center gap-2 border-b border-border/60 pb-3">
        <Label htmlFor="human-verdict" className="th-label whitespace-nowrap">
          verdict を覆す
        </Label>
        <select
          id="human-verdict"
          value={human}
          onChange={(e) => setHuman(e.target.value)}
          className="h-8 rounded-md border border-input bg-background/40 px-2 text-sm"
        >
          <option value="">覆さない(runner: {verdict || "?"} のまま)</option>
          {HUMAN_VERDICTS.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
        {human && human !== verdict ? (
          <Badge variant="outline" className="text-verdict-fail" title="覆し。保存時に規範候補が起草されます">
            覆し
          </Badge>
        ) : null}
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3">
        {fields.map(([key, label]) => (
          <div
            key={key}
            className={`flex min-h-0 flex-col gap-1 ${key === "learning" ? "flex-[2.2]" : "flex-1"}`}
          >
            <Label htmlFor={`judgment-${key}`} className="th-label">{label}</Label>
            <Textarea
              id={`judgment-${key}`}
              name={key}
              value={state[key] ?? ""}
              onChange={(e) => setState((s) => ({ ...s, [key]: e.target.value }))}
              placeholder={JUDGMENT_PLACEHOLDERS[key] ?? ""}
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
              data-1p-ignore
              className="min-h-0 flex-1 resize-none bg-background/40 text-sm leading-relaxed"
            />
          </div>
        ))}
      </div>

      <div className="space-y-2">
        {error ? <p className="text-sm text-verdict-fail">{error}</p> : null}
        <p className="text-xs text-muted-foreground">
          保存すると runs/{runId}.md へ書き戻し、checks は review-notes.md に追記、reviewed
          化・コミット・再インデックスを runner が自動実行します。⌘↵ で保存。
        </p>
        <Button type="submit" disabled={saving} className="w-full">
          {saving ? "保存中…" : "判断を保存(契約ファイルへ書き込み)"}
        </Button>
      </div>
    </form>
  );
});
