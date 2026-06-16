import type { NextConfig } from "next";

// 本番は単一オリジン。/api/* を uvicorn(FastAPI)へ rewrite し CORS を不要にする(§1.5)。
// SSE はブラウザ→FastAPI 直 + CORS の方針(技術決定)だが、通常の JSON は同一オリジン rewrite。
const API_BASE = process.env.API_BASE ?? "http://127.0.0.1:8765";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_BASE}/api/:path*` }];
  },
};

export default nextConfig;
