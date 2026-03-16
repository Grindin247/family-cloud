# Deployment Guide

## Profiles
- Dev: `docker compose --profile dev up --build`
- Prod: `docker compose --profile prod up --build -d`

## Reverse Proxy and TLS
- Nginx config at `infra/nginx/default.conf`.
- For production, place TLS cert management in proxy layer (Traefik or Nginx certbot).

## One-command deploy
`docker compose --profile prod up --build -d`

## Secrets Plan
- Keep `.env` out of git.
- Store API keys in secret manager or host-level encrypted env file.
- Rotate `JWT_SECRET` and LLM keys quarterly.
