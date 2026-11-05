import type { NextConfig } from "next";

// The design lab is local only. Its routes are `*.lab.tsx`, which are route files only when this
// flag adds that extension, so a normal build has no such routes to expose. It builds apart from
// the product so the two can never share output.
const designLab = process.env.MOODY_DESIGN_LAB === "1";

const nextConfig: NextConfig = {
  ...(designLab
    ? {
        distDir: ".next-lab",
        pageExtensions: ["lab.tsx", "tsx", "ts", "jsx", "js"],
        devIndicators: false,
        typescript: { tsconfigPath: "tsconfig.lab.json" },
      }
    : {}),
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
