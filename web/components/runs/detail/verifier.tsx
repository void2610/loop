import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { VerdictBadge } from "@/components/verdict-badge";

type Criterion = { criterion?: string; met?: boolean; evidence?: string };

function asString(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  return String(v);
}

function asCriteria(v: unknown): Criterion[] {
  if (!Array.isArray(v)) return [];
  return v.filter((c): c is Criterion => typeof c === "object" && c !== null);
}

// Verifier 判定は「種類A / 自動・別モデル」の事実表示。判断(種類B)とは視覚的に等価扱いしない。
// 推奨・色誘導を出さず、runner が書いた事実をそのまま並べるだけ(§6.7 禁止線)。
export function Verifier({ verifier }: { verifier: { [key: string]: unknown } | null }) {
  if (!verifier) return null;
  const verdict = asString(verifier.verdict);
  const confidence = asString(verifier.confidence);
  const gaming = asString(verifier.test_gaming_suspected);
  const reasons = asString(verifier.reasons);
  const criteria = asCriteria(verifier.criteria);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          Verifier の判定{" "}
          <span className="font-normal text-muted-foreground">
            (種類A / 自動・別モデル。人間の判断ではない)
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <dl className="grid grid-cols-[max-content_1fr] items-center gap-x-4 gap-y-1">
          <dt className="text-muted-foreground">verdict</dt>
          <dd>
            <VerdictBadge verdict={verdict} />
          </dd>
          <dt className="text-muted-foreground">confidence</dt>
          <dd className="font-mono">{confidence || "—"}</dd>
          <dt className="text-muted-foreground">gaming 疑い</dt>
          <dd className="font-mono">{gaming || "—"}</dd>
        </dl>
        {reasons ? (
          <pre className="whitespace-pre-wrap break-words rounded-md bg-muted/40 p-3 font-mono text-sm leading-relaxed">
            {reasons}
          </pre>
        ) : null}
        {criteria.length > 0 ? (
          <ul className="space-y-1">
            {criteria.map((c, i) => (
              <li key={i} className="flex gap-2">
                <span className={c.met ? "text-verdict-pass" : "text-verdict-fail"}>
                  {c.met ? "✓" : "✗"}
                </span>
                <span className="min-w-0 break-words">
                  {asString(c.criterion)}
                  {c.evidence ? (
                    <span className="text-muted-foreground"> — {asString(c.evidence)}</span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}
