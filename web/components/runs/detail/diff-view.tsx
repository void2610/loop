// change.patch を add/del/hunk 色分けで表示。legacy detail.html の色分けを 1:1 で写す。
// 事実(runner が書いた diff)の表示整形に閉じる。
function lineClass(line: string): string {
  if (line.startsWith("+") && !line.startsWith("+++")) return "text-verdict-pass";
  if (line.startsWith("-") && !line.startsWith("---")) return "text-verdict-fail";
  if (line.startsWith("@@") || line.startsWith("diff")) return "text-primary";
  return "";
}

export function DiffView({ patch }: { patch: string }) {
  const lines = patch.split("\n");
  return (
    <pre className="overflow-x-auto rounded-md bg-muted/40 p-3 font-mono text-xs leading-relaxed">
      {lines.map((line, i) => (
        <span key={i} className={`block ${lineClass(line)}`}>
          {line || " "}
        </span>
      ))}
    </pre>
  );
}
