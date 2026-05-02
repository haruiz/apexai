import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";

/** @type {(phase: string) => import('next').NextConfig} */
const nextConfig = (phase) => ({
  output: "export",
  distDir: phase === PHASE_DEVELOPMENT_SERVER ? ".next" : "../src/apexai/ui/static",
  trailingSlash: true,
  images: {
    unoptimized: true
  }
});

export default nextConfig;
