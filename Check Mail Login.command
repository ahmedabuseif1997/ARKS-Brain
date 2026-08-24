#!/bin/bash
# Works out which username/password combination your mail server accepts.
# Asks for the password once, tries the likely username formats, and reports
# which one works. Nothing is saved and nothing is printed back to the screen.

set -uo pipefail
cd "$(dirname "$0")"

HOST=$(grep -E '^MAIL_HOST=' .env 2>/dev/null | cut -d= -f2-)
HOST=${HOST:-example.com}

printf '\n  AHMED — mail login check\n'
printf '  ─────────────────────────────────────────────\n\n'

if [ ! -r /dev/tty ]; then
  printf '  This needs a terminal. Double-click it in Finder instead.\n\n'; exit 1
fi

# Keeps asking rather than giving up — a double-clicked window can hand the
# script an empty first read.
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

ask "  Email address: " ADDRESS
ask "  Password (not shown): " PASSWORD hidden

LOCAL="${ADDRESS%%@*}"

printf '\n  Trying %s...\n\n' "$HOST"

MAIL_HOST="$HOST" MAIL_ADDRESS="$ADDRESS" MAIL_LOCAL="$LOCAL" MAIL_PW="$PASSWORD" python3 - <<'PY'
import imaplib, os, ssl, sys

host = os.environ["MAIL_HOST"]
pw   = os.environ["MAIL_PW"]
names = [os.environ["MAIL_ADDRESS"], os.environ["MAIL_LOCAL"]]

ctx = ssl.create_default_context()
winner = None

for name in names:
    label = name if len(name) < 34 else name[:31] + "..."
    try:
        m = imaplib.IMAP4_SSL(host, 993, ssl_context=ctx)
        m.login(name, pw)
        typ, data = m.select("INBOX", readonly=True)
        count = data[0].decode() if typ == "OK" and data and data[0] else "?"
        m.logout()
        print(f"    ✓ {label:<34} WORKS — {count} messages in the inbox")
        winner = name
        break
    except imaplib.IMAP4.error as e:
        msg = str(e)
        if "AUTHENTICATIONFAILED" in msg or "Authentication failed" in msg:
            print(f"    ✗ {label:<34} rejected")
        else:
            print(f"    ✗ {label:<34} {msg[:60]}")
    except Exception as e:
        print(f"    ✗ {label:<34} {type(e).__name__}: {str(e)[:50]}")

print()
if winner:
    print("  The password is correct. Use this as your email address in Setup Mail:")
    print(f"      {winner}")
    print()
    print("  Double-click \"Setup Mail\" and enter exactly that.")
else:
    print("  Neither username was accepted, so the password itself is being refused.")
    print()
    print("  What to check, in order:")
    print("    1. Log in at webmail with the same password and see if it works there.")
    print("       If it does not, the password has changed — reset it at your host.")
    print("    2. Reset the mailbox password with whoever hosts your mail —")
    print("       on SiteGround that is Site Tools > Email > Accounts — and then")
    print("       run Setup Mail again with the new one.")
    print("    3. Confirm the address really is a mailbox and not an")
    print("       alias that forwards somewhere else — aliases have no password.")
PY

unset PASSWORD
printf '\n  Nothing was saved.\n\n'
