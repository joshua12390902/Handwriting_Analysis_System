#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Application entrypoint for the handwriting analysis system."""

import threading

import state
from tracker.pen_tracker import PenTracker
from web import app
import web.routes  # noqa: F401  # Ensure Flask routes are registered.


def _run_flask() -> None:
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)


def main() -> None:
    print("[INFO] Starting Flask at http://0.0.0.0:5000 ...")
    flask_thread = threading.Thread(target=_run_flask, daemon=True)
    flask_thread.start()

    tracker = PenTracker()
    state.app_state.set_tracker(tracker)

    try:
        tracker.run()
    except KeyboardInterrupt:
        print("\n[INFO] Keyboard interrupt received, shutting down ...")
        tracker.is_running = False


if __name__ == "__main__":
    main()
