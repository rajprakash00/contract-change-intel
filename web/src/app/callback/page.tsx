"use client";

import { useAuth0, type OAuthError } from "@auth0/auth0-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Loader2 } from "lucide-react";

// The SDK parses the authorization response on load; this page just holds a
// calm "signing in" state and carries the user back into the app.
export default function CallbackPage() {
  const { isLoading, error } = useAuth0();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !error) {
      router.replace("/");
    }
  }, [isLoading, error, router]);

  if (error) {
    // Auth0's OAuthError carries the OAuth code ("unmet_authentication_requirements",
    // "login_required", …) plus the protocol's error_description; base Error has neither.
    const oauth = error as OAuthError;
    return (
      <div className="max-w-lg space-y-3">
        <p className="text-sm font-medium text-destructive">
          Sign-in failed: {oauth.message}
        </p>
        {oauth.error && (
          <p className="font-mono text-xs text-muted-foreground">
            code: {oauth.error}
            {oauth.error_description ? ` — ${oauth.error_description}` : ""}
          </p>
        )}
        <p className="text-sm text-muted-foreground">
          This rejection came from Auth0, before our API was involved. It usually
          means the application&apos;s authentication policy in the Auth0
          dashboard demands a stronger login than the user completed.
        </p>
        <Link href="/" className="text-sm underline">
          Back to the app
        </Link>
      </div>
    );
  }
  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      Signing in…
    </p>
  );
}
