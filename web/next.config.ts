import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output: a small self-contained server for the Docker image on the Synology.
  output: "standalone",
  poweredByHeader: false,
};

export default nextConfig;
