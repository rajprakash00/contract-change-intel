"use client";

import { useAuth0 } from "@auth0/auth0-react";
import { createContext, useContext, useMemo } from "react";

import { createApi, type Api } from "@/lib/api";

// One Api instance per auth session; components call useApi() and stay
// oblivious to how the bearer token is obtained.
const ApiContext = createContext<Api | null>(null);

export function ApiContextProvider({ children }: { children: React.ReactNode }) {
  const { getAccessTokenSilently, loginWithRedirect } = useAuth0();
  const api = useMemo(
    () =>
      createApi(async () => {
        try {
          return await getAccessTokenSilently();
        } catch (error) {
          // Silent refresh failed because the session is really gone
          // (login_required / consent_required) — send the user back to
          // login instead of letting every request 401.
          const code = (error as { error?: string }).error;
          if (code === "login_required" || code === "consent_required") {
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
