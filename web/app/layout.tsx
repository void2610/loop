import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "loop",
  description: "loop — run triage / monitor / dashboard",
};

// 全ワークストリーム分のナビを先置きする(0.5 ゲートの責務)。
// リンク先が未実装(404)でも可。後続 merge が layout.tsx を触らずに済むのが狙い。
const NAV: { href: string; label: string }[] = [
  { href: "/runs", label: "Runs" }, // P1-A 一覧
  { href: "/tasks", label: "Tasks" }, // P1-C TODO
  { href: "/monitor", label: "Monitor" }, // P2 SSE ライブ
  { href: "/dashboard", label: "Dashboard" }, // P3 分析
];

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ja" className="dark" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">
        <div className="flex min-h-screen flex-col">
          <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur">
            <div className="container flex h-14 items-center gap-6">
              <Link href="/" className="text-sm font-bold tracking-tight">
                loop
              </Link>
              <nav className="flex items-center gap-1 text-sm">
                {NAV.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="rounded-md px-3 py-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
                  >
                    {item.label}
                  </Link>
                ))}
              </nav>
            </div>
          </header>
          <main className="container flex-1 py-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
