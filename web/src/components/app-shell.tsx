"use client";

import { useAuth0 } from "@auth0/auth0-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { FileDiff, LogOut, ScrollText } from "lucide-react";

import { roleFromClaims } from "@/lib/roles";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const NAV_ITEMS = [
  { href: "/", label: "Documents", icon: FileDiff },
  { href: "/review-items", label: "Review queue", icon: ScrollText },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, isAuthenticated, isLoading, loginWithRedirect, logout } = useAuth0();
  const pathname = usePathname();
  const role = roleFromClaims(user);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b bg-card">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-8 px-6">
          <Link href="/" className="font-serif text-lg font-semibold tracking-tight">
            Contract Change-Impact Intelligence
          </Link>
          <nav className="flex items-center gap-1">
            {NAV_ITEMS.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={
                  pathname === item.href
                    ? "rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-foreground"
                    : "rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                }
              >
                {item.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            {isLoading ? null : isAuthenticated ? (
              <>
                {role && <Badge variant="secondary">{role}</Badge>}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    logout({ logoutParams: { returnTo: window.location.origin } })
                  }
                >
                  <LogOut aria-hidden />
                  Sign out
                </Button>
              </>
            ) : (
              <Button size="sm" onClick={() => loginWithRedirect()}>
                Sign in
              </Button>
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-10">{children}</main>
    </div>
  );
}
