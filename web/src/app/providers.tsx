"use client";

import { Auth0Provider } from "@auth0/auth0-react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as Sentry from "@sentry/browser";
import { ThemeProvider } from "next-themes";
import { useEffect, useMemo, useState } from "react";

import { ApiContextProvider } from "@/lib/api-context";
import { Toaster } from "@/components/ui/sonner";

// Auth0 SPA login (docs/w6-decisions.md #2): PKCE, silent refresh with
// rotating refresh tokens. Values come from the Auth0 SPA application
// registration (see .env.example).
//
// The session must survive a page refresh: localstorage cache + refresh
// tokens let the SDK renew on load without the prompt=none iframe, which
// browsers with partitioned third-party cookies block — without this a
// signed-in user refreshing `/` fails the silent check and would be shown
// the landing page. offline_access is required for refresh tokens; the
// Auth0 API needs "Allow Offline Access" (on by default).
const domain = process.env.NEXT_PUBLIC_AUTH0_DOMAIN;
const clientId = process.env.NEXT_PUBLIC_AUTH0_CLIENT_ID;
const audience = process.env.NEXT_PUBLIC_AUTH0_AUDIENCE;

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: 1, staleTime: 10_000, refetchOnWindowFocus: false },
        },
      }),
  );

  // Error capture only, client-side (the failures the API logs never see —
  // dead-session states, query-level errors). No DSN → disabled; same
  // posture as the backend's empty-DSN no-op. An effect, not a render-time
  // init: client components are prerendered on the server, where there is
  // no window — and a state-initializer init would never run again after
  // hydration.
  useEffect(() => {
    if (!process.env.NEXT_PUBLIC_SENTRY_DSN) return;
    Sentry.init({
      dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
      // Separates prod events from local ones in one project.
      environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT,
      // Window errors and unhandled rejections; no tracing.
      tracesSampleRate: 0,
      allowUrls: [window.location.origin],
    });
  }, []);

  const authEnabled = Boolean(domain && clientId && audience);
  const app = useMemo(() => {
    const content = (
      <ApiContextProvider>
        {children}
        <Toaster position="bottom-right" />
      </ApiContextProvider>
    );
    // Unconfigured auth fails loudly instead of rendering a UI that cannot
    // reach the API — same posture as the backend's no-"auth off" mode.
    if (!authEnabled) {
      return (
        <div className="flex min-h-screen items-center justify-center p-8">
          <div className="max-w-md text-center text-sm text-muted-foreground">
            Auth0 is not configured: set NEXT_PUBLIC_AUTH0_DOMAIN,
            NEXT_PUBLIC_AUTH0_CLIENT_ID and NEXT_PUBLIC_AUTH0_AUDIENCE (see
            .env.example).
          </div>
        </div>
      );
    }
    return (
      <Auth0Provider
        domain={domain!}
        clientId={clientId!}
        useRefreshTokens
        cacheLocation="localstorage"
        authorizationParams={{
          audience: audience!,
          scope: "openid profile email offline_access",
          redirect_uri:
            typeof window === "undefined"
              ? undefined
              : `${window.location.origin}/callback`,
        }}
      >
        {content}
      </Auth0Provider>
    );
  }, [authEnabled, children]);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
        {app}
      </ThemeProvider>
    </QueryClientProvider>
  );
}
