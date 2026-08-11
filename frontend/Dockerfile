# syntax=docker/dockerfile:1
#
# Production Dockerfile for the frontend. Build from frontend/ as the
# context:
#
#   docker build -t vision-language-robotics-frontend frontend/
#
# (docker-compose.yml at the repo root does this automatically.)
#
# Two stages: (1) install deps and produce a real Vite production
# build (`npm run build` -- the same `tsc --noEmit && vite build` used
# in CI/locally, so a broken build fails here too, not just in CI),
# (2) serve the built static assets (including the canonical MILO
# character PNGs under /assets/milo/, copied verbatim by Vite from
# public/ -- see frontend/src/state/miloState.ts) from nginx.
#
# Why the frontend still only ever calls relative URLs
# ------------------------------------------------------
# The app's API client (`src/api/client.ts`) deliberately never builds
# an absolute backend URL -- see vite.config.ts's dev-proxy docstring.
# In dev, Vite's own proxy forwards `/api` and `/health` to the
# backend; in this image, nginx.conf.template plays the identical role
# via a reverse-proxy `location` block, so the same built bundle works
# unmodified in both places.

FROM node:20-slim AS build
WORKDIR /app

# Dependency manifest first so this layer is cached unless it changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

# Templated so the backend's address is a deployment-time choice
# (docker-compose sets it to the backend service's DNS name), not
# baked into the image. nginx's own entrypoint runs envsubst over
# every file in /etc/nginx/templates/*.template using only the
# container's actual environment variables (not nginx's own runtime
# variables like $uri/$host, which are never shell env vars) -- see
# https://hub.docker.com/_/nginx "Using environment variables in nginx
# configuration". BACKEND_ORIGIN's default matches the compose service
# name (`backend`) so `docker compose up` works with no extra config.
ENV BACKEND_ORIGIN=http://backend:8000
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://localhost/ || exit 1
