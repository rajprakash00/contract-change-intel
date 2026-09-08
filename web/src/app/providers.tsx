"use client";

import { Auth0Provider } from "@auth0/auth0-react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { ApiContextProvider } from "@/lib/api-context";
import { Toaster } from "@/components/ui/sonner";

// Auth0 SPA login (docs/w6-decisions.md #2): PKCE, silent refresh with
// rotating refresh tokens, in-memory token cache. Values come from the
// Auth0 SPA application registration (see .env.example).
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
        authorizationParams={{
          audience: audience!,
          scope: "openid profile email",
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

  return <QueryClientProvider client={queryClient}>{app}</QueryClientProvider>;
}
