import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// front-matter を素の事実として羅列表示する。値は文字列化のみ(整形・解釈を加えない)。
function toText(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

export function FrontMatter({ fm }: { fm: { [key: string]: unknown } }) {
  const entries = Object.entries(fm);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">front-matter</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
          {entries.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="font-mono text-muted-foreground">{k}</dt>
              <dd className="min-w-0 break-words font-mono">{toText(v) || "—"}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}
