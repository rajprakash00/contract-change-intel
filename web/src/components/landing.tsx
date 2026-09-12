"use client";

// Static landing page for logged-out visitors (issue #20): the entry state,
// no auto-redirect to the identity provider. There is no logged-out view of
// the app — every route is gated — so both CTAs converge on the PKCE
// redirect and land back in the app via /callback.
import { BrandMark } from "@/components/brand";
import { Button } from "@/components/ui/button";

export function LandingPage({ onSignIn }: { onSignIn: () => void }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 px-6 text-center">
      <BrandMark className="size-16 rounded-xl" />
      <div className="space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight">
          Contract Change-Impact Intelligence
        </h1>
        <p className="mx-auto max-w-md text-base text-muted-foreground">
          Upload an agreement, upload its amendment, see what changed and what it
          affects.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <Button size="lg" onClick={onSignIn}>
          Sign in
        </Button>
        <Button size="lg" variant="outline" onClick={onSignIn}>
          Go to app
        </Button>
      </div>
    </div>
  );
}
