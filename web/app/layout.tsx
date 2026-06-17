import type { Metadata } from "next";
import Link from "next/link";
import { Repeat } from "lucide-react";

import { SiteNav } from "@/components/site-nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "loop — Loop Engineering",
  description: "loop — run triage / monitor / dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ja" className="dark" suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground antialiased">
        <div className="flex min-h-screen flex-col">
          <header className="sticky top-0 z-40 border-b border-border/80 bg-background/70 backdrop-blur-xl">
            <div className="mx-auto flex h-14 w-full max-w-[1400px] items-center gap-6 px-4 sm:px-6">
              <Link
                href="/"
                className="flex items-center gap-2 font-semibold tracking-tight transition-opacity hover:opacity-80"
              >
                <span className="flex size-7 items-center justify-center rounded-lg bg-primary/15 text-primary ring-1 ring-primary/25">
                  <Repeat className="size-4" aria-hidden />
                </span>
                <span>loop</span>
              </Link>
              <SiteNav />
            </div>
          </header>
          <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-8 sm:px-6">
            {children}
          </main>
          <footer className="border-t border-border/60 py-5">
            <div className="mx-auto w-full max-w-[1400px] px-4 text-xs text-muted-foreground sm:px-6">
              loop — Loop Engineering 計測配管 · 種類A は自動 / 判断(種類B)は人間が書く
            </div>
          </footer>
        </div>
      </body>
    </html>
  );
}
