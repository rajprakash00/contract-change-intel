"use client";

import { useAuth0 } from "@auth0/auth0-react";
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
    return <p className="text-sm text-destructive">Sign-in failed: {error.message}</p>;
  }
  return (
    <p className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      Signing in…
    </p>
  );
}
