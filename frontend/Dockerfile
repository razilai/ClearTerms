# syntax=docker/dockerfile:1

# --- build stage: compile the SPA to static assets ---
FROM node:22-slim AS build
WORKDIR /app

# Install deps first (cached until the lockfile changes), then the source.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build          # tsc -b && vite build → /app/dist

# --- serve stage: nginx serving the static build ---
# Unprivileged variant: runs as non-root (uid 101) and listens on 8080, so no
# root and no privileged-port bind. nginx.conf listens on 8080 to match.
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
