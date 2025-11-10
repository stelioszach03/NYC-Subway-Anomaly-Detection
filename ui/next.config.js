/** @type {import('next').NextConfig} */
const backend = process.env.UI_BACKEND_URL || 'http://localhost:8000';
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${backend}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
