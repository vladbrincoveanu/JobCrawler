/** @type {import('next').NextConfig} */
const nextConfig = {
  // better-sqlite3 is a native module — mark as external for server components.
  serverExternalPackages: ["better-sqlite3"],
};

export default nextConfig;
