import type { NextConfig } from "next";

// Same-origin serving (docs/w6-decisions.md #1): the browser always says
// /api/... and dev proxies to the bare API, stripping the prefix. Prod
// path-routes at the ALB instead — no CORS anywhere, root_path lives in the
// API's Settings (docs/w6-decisions.md #6).
const nextConfig: NextConfig = {
  async rewrites() {
    const apiOrigin = process.env.API_ORIGIN ?? "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${apiOrigin}/:path*` }];
  },
};

export default nextConfig;
