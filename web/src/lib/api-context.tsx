"use client";

import { useAuth0 } from "@auth0/auth0-react";
import { createContext, useContext, useMemo } from "react";

import { createApi, type Api } from "@/lib/api";

// One Api instance per auth session; components call useApi() and stay
// oblivious to how the bearer token is obtained.
const ApiContext = createContext<Api | null>(null);

// Codes thrown by auth0-spa-js when silent refresh can never succeed again:
// the Auth0 session is gone (login_required/consent_required) or the refresh
// token is dead — missing from cache, or rotated-away and revoked wholesale
// by Auth0's reuse detection (missing_refresh_token/invalid_grant). Anything
// else (timeout, network) is transient and must not bounce the user to login.
const SESSION_LOST_CODES = new Set([
  "login_required",
  "consent_required",
  "missing_refresh_token",
  "invalid_grant",
  "invalid_refresh_token",
]);

export function isSessionLost(error: unknown): boolean {
  const code = (error as { error?: string } | null)?.error;
  return code !== undefined && SESSION_LOST_CODES.has(code);
}

export function ApiContextProvider({ children }: { children: React.ReactNode }) {
  const { getAccessTokenSilently, loginWithRedirect } = useAuth0();
  const api = useMemo(
    () =>
      createApi(async () => {
        try {
          return await getAccessTokenSilently();
        } catch (error) {
          // Silent refresh failed and can never recover — send the user
          // back to login instead of letting every request fail (they
          // render as "Is the API running?", which is misleading: the API
          // is up, the session is not).
          if (isSessionLost(error)) {
            await loginWithRedirect();
          }
          throw error;
        }
      }),
    [getAccessTokenSilently, loginWithRedirect],
  );
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
}

export function useApi(): Api {
  const api = useContext(ApiContext);
  if (!api) {
    throw new Error("useApi must be used inside ApiContextProvider");
  }
  return api;
}
