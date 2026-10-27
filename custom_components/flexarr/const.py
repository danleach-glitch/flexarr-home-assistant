"""Constants for the Flexarr integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "flexarr"

# Fired on Home Assistant's event bus for every playback change Flexarr reports.
EVENT_PLAYBACK: Final = "flexarr_playback"

# Flexarr's playback event kinds, as they're named in triggers and in EVENT_PLAYBACK's "type".
PLAYBACK_EVENTS: Final = ("started", "paused", "resumed", "credits", "ended", "stopped")

# The device list (who's online, what's playing) is fetched this often, and straight after any playback event.
SCAN_INTERVAL: Final = timedelta(seconds=30)

# Waits between tries when the event stream drops, longest last.
RECONNECT_DELAYS: Final = (1, 5, 15, 30, 60)
