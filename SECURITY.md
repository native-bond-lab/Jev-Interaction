# Security

Jev-Interaction runs a local server that holds your provider keys. What it does to keep them yours:

- Keys live only in your `.env` (written with mode 0600). They are never sent anywhere except to the provider they
  belong to, and the settings page never shows a saved key again.
- The settings page writes only when the request comes from this server's own page on this machine: loopback client,
  loopback `Host` header (against DNS rebinding), the same `Origin`, JSON only (against cross-site form posts).
- A call (`/ws`) can be opened only from the server's own origin, or one listed in `ALLOWED_ORIGINS`.
- Docker: `docker compose` binds the port to `127.0.0.1`. Do not publish it on a public interface with keys inside;
  for a public demo set `MAX_CONCURRENT_CALLS` and `MAX_CALL_SECONDS`, since every call is billed to your keys.
- Call logs (`runs/`) contain what callers said. Keep them private, and strip them before sharing.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting on this repository
(Security → Report a vulnerability), and we will answer within a few days.
