# Security and Access Control

## Auth model

- MCP endpoint `/mcp` requires `Authorization: Bearer <token>`.
- Token is an opaque random string returned by `/auth/login`.
- Only token hash is stored in DB (`sessions.token_hash`).
- Token TTL is 3600 seconds.

## Password model

- Passwords are hashed with PBKDF2-HMAC-SHA256.
- Iterations: `600_000`.
- Stored format: `pbkdf2_sha256$<iterations>$<salt_hex>$<digest_hex>`.

## Login hardening

- Username/password validation and constant-time compare for password checks.
- Per-user lockout after 5 failed attempts.
- Lockout duration: 15 minutes.

## Bootstrap admin

- Initial admin creation is only possible via CLI:
  - `python -m server.bootstrap_admin`
- It is interactive and one-time only (before first user exists).

## Authorization model

Authorization is enforced for both tool discovery and tool calls:

- Admin users: all tools.
- Non-admin users:
  - union of role grants (`role_tools` via `user_roles`)
  - overridden by user-specific grants/denies (`user_tools`)

`tools/list` is filtered per user and `tools/call` is checked per request.

## Admin operations

Admin endpoints are HTTP-only (`POST /admin/{operation}`):

- User lifecycle: `create_user`, `set_user_active`, `reset_password`,
  `revoke_sessions`
- Role lifecycle: `create_role`, `assign_role`, `remove_role`
- Permissions: `grant_role_tool`, `revoke_role_tool`, `grant_user_tool`,
  `deny_user_tool`, `clear_user_tool`

## Auditing

Security-relevant events are recorded in `security_events`:

- login success/failure
- logout
- admin mutations
- tool calls and tool denials

Sensitive values are not logged in plaintext (passwords/tokens).

## Deployment recommendations

- For remote environments, require HTTPS at reverse proxy.
- Set `ERP_PUBLIC_URL` to externally reachable HTTPS origin.
- Restrict access to `/admin/*` and apply rate limits on `/auth/login`.
- Keep application container port private where possible.
