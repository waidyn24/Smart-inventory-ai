// Same-origin API proxy for the all-in-one cloud container.
// Local Docker Compose can continue using NEXT_PUBLIC_API_URL=http://localhost:8000.
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  async rewrites() {
    return [{ source: '/api/:path*', destination: 'http://127.0.0.1:8000/:path*' }];
  },
};
export default nextConfig;
