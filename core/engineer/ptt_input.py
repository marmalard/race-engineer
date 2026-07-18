"""PTT wheel-button input: pygame joystick read + pure edge detection.

open_joystick() returns a zero-arg poll callable (True while the button
is held) or None when pygame/the wheel is absent -- PTT then disables
with a visible startup line. PTTButton is the pure press/release edge
detector the tick loop feeds; it is the tested part. Find your button
index with scripts/probe_ptt_button.py.
"""

import logging
from typing import Callable

logger = logging.getLogger(__name__)


class PTTButton:
    """Pure edge detector: feed(held) -> 'press' | 'release' | None."""

    def __init__(self) -> None:
        self._held = False

    def feed(self, held: bool) -> str | None:
        if held and not self._held:
            self._held = True
            return "press"
        if not held and self._held:
            self._held = False
            return "release"
        return None


def open_joystick(button_index: int) -> Callable[[], bool] | None:
    """Poll callable for joystick 0's button, or None when unavailable."""
    try:
        import pygame
        pygame.init()
        pygame.joystick.init()
        if pygame.joystick.get_count() == 0:
            logger.warning("No joystick found; PTT disabled")
            return None
        js = pygame.joystick.Joystick(0)
        js.init()

        def poll() -> bool:
            pygame.event.pump()
            return bool(js.get_button(button_index))

        return poll
    except Exception:
        logger.warning("pygame unavailable; PTT disabled", exc_info=True)
        return None
