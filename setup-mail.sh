#!/bin/bash
# One-time mail setup for AHMED.
#
# Asks for the mailbox address and password, checks them against the server,
# and only then saves anything. The password goes into the macOS Keychain —
# encrypted at rest, unlocked by your macOS login. It is never written to a
# file, never shown on screen, and never lands in shell history.
#
# Run once. After that AHMED reads it at startup and you are never asked again.

set -uo pipefail
cd "$(dirname "$0")"

SERVICE="ahmed-mail"
ENV_FILE=".env"

printf '\n  AHMED — mail setup\n'
printf '  ─────────────────────────────────────────────\n\n'

# Read from the terminal itself rather than whatever stdin happens to be. When
# launched by double-clicking the .command file, stdin can arrive already at
# end-of-file, which made the first prompt return empty instantly and the
# script give up before anything could be typed.
if [ ! -r /dev/tty ]; then
  printf '  This needs a terminal. Double-click "Setup Mail" in Finder instead.\n\n'
  exit 1
fi

# ask <prompt> <varname> [hidden] — keeps asking until something is entered.
ask() {
  local prompt="$1" __var="$2" hidden="${3:-}" value=""
  while true; do
    printf '%s' "$prompt" > /dev/tty
    if [ "$hidden" = "hidden" ]; then
      IFS= read -r -s value < /dev/tty || value=""
      printf '\n' > /dev/tty
    else
      IFS= read -r value < /dev/tty || value=""
    fi
    value="$(printf '%s' "$value" | sed -E 's/^[[:space:]]+|[[:space:]]+$//g')"
    [ -n "$value" ] && break
    printf '  (nothing entered — type it, or press Control-C to cancel)\n' > /dev/tty
  done
  printf -v "$__var" '%s' "$value"
}

MAIL_HOST_VALUE=$(grep -E '^MAIL_HOST=' "$ENV_FILE" 2>/dev/null | cut -d= -f2-)
MAIL_HOST_VALUE=${MAIL_HOST_VALUE:-example.com}

# Anything already saved is only offered as a default if it looks like an
# address — a half-finished earlier run must not come back as a suggestion.
CURRENT_USER=$(grep -E '^MAIL_USER=' "$ENV_FILE" 2>/dev/null | cut -d= -f2-)
case "$CURRENT_USER" in
  *@*.*) ;;                       # plausible
  *) CURRENT_USER="" ;;
esac

ATTEMPT=0
while true; do
ATTEMPT=$((ATTEMPT + 1))

while true; do
  if [ -n "$CURRENT_USER" ]; then
    ask "  Email address [$CURRENT_USER]: " ADDRESS
  else
    ask "  Email address: " ADDRESS
  fi
  case "$ADDRESS" in
    *@*.*) break ;;
    *) printf '  That does not look like an email address — try again.\n' ;;
  esac
done

printf '\n  Password will not be shown as you type — that is normal.\n'
ask "  Mailbox password: " PASSWORD hidden

# ── Check BEFORE saving. A failed login used to leave the address written to
#    .env and a wrong password sitting in the Keychain, while telling you
#    nothing had been saved. Nothing is persisted until the server accepts it.
printf '\n  Checking with %s...\n' "$MAIL_HOST_VALUE"
RESULT=$(
  MAIL_HOST="$MAIL_HOST_VALUE" \
  MAIL_USER="$ADDRESS" \
  MAIL_PASSWORD="$PASSWORD" \
  python3 ecosine-mail.py list <<< '{"limit": 1}'
)

VERDICT=$(printf '%s' "$RESULT" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("FAIL|The mail helper gave no usable answer."); raise SystemExit
if d.get("error"):
    print("FAIL|" + d["error"])
else:
    print("OK|%d unread in the inbox." % d.get("total_matching", 0))
')

STATUS=${VERDICT%%|*}
MESSAGE=${VERDICT#*|}

if [ "$STATUS" != "OK" ]; then
  unset PASSWORD
  printf '\n  ✗ %s\n' "$MESSAGE"
  printf '\n  Nothing was saved.\n'
  if [ "$ATTEMPT" -ge 3 ]; then
    printf '\n  Three attempts. Check the password in webmail before trying again,\n'
    printf '  or reset it at your host and come back.\n\n'
    exit 1
  fi
  printf '  The password is hidden as you type, so a slip is easy — try again.\n'
  printf '  (Control-C to give up.)\n\n'
  CURRENT_USER="$ADDRESS"      # keep the address, it was accepted
  continue
fi

break
done

# ── Accepted. Now it is safe to keep. ────────────────────────────────────
security add-generic-password -a "$USER" -s "$SERVICE" -w "$PASSWORD" -U
unset PASSWORD

if grep -qE '^MAIL_USER=' "$ENV_FILE"; then
  sed -i '' -E "s|^MAIL_USER=.*|MAIL_USER=${ADDRESS}|" "$ENV_FILE"   # BSD sed needs ''
else
  printf '\nMAIL_USER=%s\n' "$ADDRESS" >> "$ENV_FILE"
fi
# Clear any password left in the file by an earlier attempt — the Keychain holds it now.
sed -i '' -E "s|^MAIL_PASSWORD=.+|MAIL_PASSWORD=|" "$ENV_FILE"
chmod 600 "$ENV_FILE"

printf '\n  ✓ Connected. %s\n' "$MESSAGE"
printf '  Password saved to your Keychain as "%s".\n' "$SERVICE"
printf '  Address saved to .env — the password was not.\n'

# ── Restart the server so it picks this up, rather than telling you to. ──
if pgrep -f 'node ecosine-server.js' > /dev/null; then
  printf '\n  Restarting AHMED...\n'
  pkill -f 'node ecosine-server.js'
  sleep 1
  nohup node ecosine-server.js > /tmp/ahmed-server.log 2>&1 &
  sleep 3
  grep -i '  Mail:' /tmp/ahmed-server.log | sed 's/^/  /'
else
  printf '\n  Start AHMED when you are ready:  node ecosine-server.js\n'
fi

printf '\n  Done.\n\n'
