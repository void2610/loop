import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

// Implementer の最終出力(事実テキスト)。runner も GUI も再要約しない(§2.2 / §6.7)。
export function Summary({ summary }: { summary: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          エージェントがやったこと{" "}
          <span className="font-normal text-muted-foreground">
            (Implementer の最終出力)
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <pre className="whitespace-pre-wrap break-words font-mono text-sm leading-relaxed">
          {summary || "(最終出力なし)"}
        </pre>
      </CardContent>
    </Card>
  );
}
