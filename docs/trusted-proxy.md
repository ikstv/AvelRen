# Trusted proxy boundary

Production traffic follows `Internet → Caddy → API`. The API container has no
published host port; Caddy is the sole public ingress.

Caddy removes the client-supplied `X-Forwarded-For` and
`X-AvelRen-Client-IP` headers, then sets `X-AvelRen-Client-IP` from the socket
peer address. The API rate limiter trusts only that dedicated internal header.
If it is absent or malformed, the limiter falls back to the transport peer;
it never uses `X-Forwarded-For` supplied by a client.
