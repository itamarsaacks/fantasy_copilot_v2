import type { NextConfig } from "next";

/**
 * Backend lives at localhost:8000. We proxy backend routes through the Next.js
 * dev server so frontend + backend look like the same origin to the browser.
 *
 * Why this matters: in dev with ngrok tunneling the FRONTEND, Yahoo OAuth
 * redirects to https://<ngrok>/auth/yahoo/callback, which is handled by these
 * rewrites and forwarded to the backend. Cookies set by the backend then live
 * on the ngrok domain — same domain the browser is using — so the frontend
 * can read them on subsequent requests.
 *
 * The same proxy path also works at localhost:3000 (no ngrok), in which case
 * cookies live on `localhost`, also fine.
 */

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    // Note: /chat is a frontend PAGE, so we proxy the API call under /api/chat
    // to avoid the collision (Next.js rewrites win over filesystem routing for
    // POST too, but a literal /chat source would intercept the GET that loads
    // the page, breaking it on direct visit). /auth, /admin, /health don't
    // collide with any frontend page so they can stay flat.
    return [
      { source: "/auth/:path*", destination: `${BACKEND_URL}/auth/:path*` },
      { source: "/api/chat", destination: `${BACKEND_URL}/chat` },
      { source: "/admin/:path*", destination: `${BACKEND_URL}/admin/:path*` },
      { source: "/health", destination: `${BACKEND_URL}/health` },
    ];
  },
  // Allow ngrok tunneling — accept whatever Host header it sends.
  // Remove if/when this becomes a concern in production.
  allowedDevOrigins: ["*.ngrok-free.dev", "*.ngrok.io"],
};

export default nextConfig;
