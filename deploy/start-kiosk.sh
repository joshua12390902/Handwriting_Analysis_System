#!/usr/bin/env bash
# Wait for the backend to come up, then open the writing UI full-screen.
# Used by the desktop autostart entry (deploy/handwriting-kiosk.desktop) so the
# Orin boots straight into the demo with no terminal steps.
set -u

URL="http://localhost:5000"

# Wait (up to ~60s) for the Flask server to answer before launching the browser.
for _ in $(seq 1 60); do
    if curl -fsS -o /dev/null "$URL"; then
        break
    fi
    sleep 1
done

# Pick whichever Chromium binary exists on this image.
BROWSER="$(command -v chromium-browser || command -v chromium || echo chromium-browser)"

exec "$BROWSER" \
    --kiosk \
    --app="$URL" \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --check-for-update-interval=31536000
