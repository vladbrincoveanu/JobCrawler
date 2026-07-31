# Dashboard Dockerfile — Next.js dev server
# Used by docker-compose for local development.

FROM node:20-alpine

WORKDIR /app

# Install deps first (cache layer)
COPY package.json package-lock.json* ./
RUN npm install

# Copy source (changes often; keep layer above cached)
COPY . .

EXPOSE 3011

# next dev defaults to 3000; without this it ignores EXPOSE/the compose
# 3011:3011 mapping and the container is unreachable from the host.
ENV PORT=3011

# Use host.docker.internal so the container can reach the host's
# Postgres on 5433 (compose maps host:5433 → postgres:5432).
ENV DATABASE_URL=postgresql://jobcrawler:dev@host.docker.internal:5433/jobcrawler

CMD ["npm", "run", "dev"]