#!/bin/sh
set -eu

HTPASSWD_FILE="/etc/nginx/.htpasswd"

if [ -z "${MBK_AUTH_USERNAME:-}" ] || [ -z "${MBK_AUTH_PASSWORD:-}" ]; then
  echo "ERROR: MBK_AUTH_USERNAME and MBK_AUTH_PASSWORD must be set for MBK frontend auth" >&2
  exit 1
fi

# Generate the nginx Basic Auth password file from runtime env.
# The password is read from stdin so it is not exposed through process arguments.
printf '%s\n' "$MBK_AUTH_PASSWORD" | htpasswd -cBi "$HTPASSWD_FILE" "$MBK_AUTH_USERNAME" >/dev/null
chmod 644 "$HTPASSWD_FILE"
