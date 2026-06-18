"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BookOpen, LayoutDashboard, ListChecks, Repeat } from "lucide-react";

import { cn } from "@/lib/utils";

const NAV = [
  { href: "/runs", label: "Runs", icon: Repeat },
  { href: "/tasks", label: "Tasks", icon: ListChecks },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
] as const;

export function SiteNav() {
  const pathname = usePathname();
  return (
    <nav className="flex items-center gap-1 text-sm">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 font-medium transition-colors",
              active
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
            )}
          >
            <Icon className="size-4" aria-hidden />
            <span className="hidden sm:inline">{label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
