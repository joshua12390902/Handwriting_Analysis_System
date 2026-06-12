# Orin Nano demo deployment (boot-to-UI + crash recovery)

Turns the manual "SSH → activate venv → run app.py → open Chromium" ritual into
an unattended kiosk: the Orin boots straight into the writing UI, and the
backend auto-restarts if it crashes mid-demo.

## One-time install (on the Orin)

```bash
cd ~/Handwriting_Analysis_System

# 1) Backend as a restart-always user service
mkdir -p ~/.config/systemd/user
cp deploy/handwriting.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now handwriting.service
sudo loginctl enable-linger $USER          # keep running with no SSH session open

# 2) Kiosk browser on login
chmod +x deploy/start-kiosk.sh
mkdir -p ~/.config/autostart
cp deploy/handwriting-kiosk.desktop ~/.config/autostart/

# 3) Enable desktop auto-login so the kiosk fires on boot:
#    GNOME: Settings → Users → Automatic Login → On
```

Reboot. The Orin should come up, start the backend, wait for port 5000, and open
the writing UI full-screen.

## Handy commands
- Backend logs:    `journalctl --user -u handwriting -f`
- Restart backend: `systemctl --user restart handwriting`
- Stop kiosk:      `Alt+F4` (or `Ctrl+W`)
- Disable kiosk:   `rm ~/.config/autostart/handwriting-kiosk.desktop`

## Notes
- The `.desktop` Exec path assumes the repo is at `/home/penyi/Handwriting_Analysis_System`.
  Edit it if your username/path differ.
- AI feedback still needs network to the lab Ollama (140.113.110.42); off-network
  the app falls back to rule-based feedback within `OLLAMA_TIMEOUT` (default 8s).
