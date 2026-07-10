/** @type {import('next').NextConfig} */
const nextConfig = {
  // standalone-сборка для лёгкого multi-stage Docker-образа.
  output: "standalone",
  reactStrictMode: true,
  // Базовый URL API (сервер-сайд рендер публичных страниц событий, M6).
  env: {
    API_BASE_URL: process.env.API_BASE_URL ?? "http://api:8000",
  },
};

export default nextConfig;
