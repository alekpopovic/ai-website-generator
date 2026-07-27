# Authentication Security

## Credential and session model

Passwords are validated for length and character diversity and hashed with Argon2id. Hashing and
verification run outside the asynchronous request event loop. Passwords, raw action tokens, raw
refresh tokens, and access tokens are excluded from structured representations and audit details.

Access tokens are signed with a deployment secret, fixed issuer and audience, a five-minute default
lifetime, and user and session identifiers. Angular holds an access token only in memory. It never
uses `localStorage` or `sessionStorage` for credentials.

Refresh tokens are high-entropy opaque values. PostgreSQL stores only their SHA-256 digests, family,
expiry, replacement link, and lifecycle state. Each refresh atomically locks and revokes the old
record before issuing its replacement. Reuse of any inactive token revokes the entire family and
records an audit event; that security transition is committed before the `401` response is sent.

The refresh cookie is HttpOnly, scoped to `/api/v1/auth`, and configured as `SameSite=Lax` or
`Strict`. Secure cookies are mandatory in staging and production. Explicit credentialed CORS
origins and same-site POST behavior form the CSRF boundary; deployments must keep the web and API
on same-site HTTPS origins. Authentication responses are `Cache-Control: no-store`.

## Verification and recovery

Registration creates a single-use, expiring email-verification token. Unverified accounts cannot
sign in. Password-reset requests always return the same acknowledgement whether an account exists.
Issuing a new reset consumes prior pending reset tokens; consuming a reset changes the password and
revokes every refresh session. Only action-token hashes are stored. Tokens are carried in URL
fragments so browsers do not send them in HTTP request targets or referrer headers.

Development email is delivered to the Compose Mailpit SMTP service and can be inspected at
<http://127.0.0.1:8025>. Production must configure an authenticated TLS SMTP relay or replace the
mailer boundary with an approved provider adapter.

## Abuse controls and auditing

Login attempts are limited by a Redis atomic fixed window keyed with an HMAC of normalized email and
client IP. The endpoint fails closed when the rate-limit store is unavailable. Credential failures
use a dummy Argon2id verification path to reduce account enumeration. Password-reset requests are
enumeration-safe.

Audit records cover registration, login success and failure, refresh rotation and reuse, session
logout, all-session logout, email verification, and password-reset request/completion. Audit details
contain identifiers and safe reason codes, never credentials or tokens.

## Operational requirements

- Generate `SECURITY_ACCESS_TOKEN_SECRET` with at least 32 bytes of cryptographic randomness and
  supply it through a secret manager.
- Use HTTPS and `SECURITY_REFRESH_COOKIE_SECURE=true` outside local development.
- Monitor `auth.login_failed`, `auth.refresh_reuse_detected`, and rate-limit responses.
- Treat signing-key rotation and suspected token theft as incident-response procedures that revoke
  affected refresh families or all user sessions.
- Run database migrations before enabling the authentication routes.
