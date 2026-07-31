/** @type {import('next').NextConfig} */
const nextConfig = {
  // Separate build dir for test runs, so a `next dev` server running against
  // this checkout cannot rewrite .next underneath a `next start` the test suite
  // is booting -- which fails as "Could not find a production build".
  distDir: process.env.NEXT_DIST_DIR || ".next",
};

export default nextConfig;
