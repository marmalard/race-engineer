"""Find the wheel button index for --ptt-button. Hold each button; the
index prints when it goes down. Ctrl+C to quit.

    .venv/Scripts/python.exe scripts/probe_ptt_button.py
"""

import time

import pygame

pygame.init()
pygame.joystick.init()
if pygame.joystick.get_count() == 0:
    raise SystemExit("No joystick found -- is the wheel on?")
js = pygame.joystick.Joystick(0)
js.init()
print(f"{js.get_name()}: {js.get_numbuttons()} buttons. Press one...")
prev = set()
while True:
    pygame.event.pump()
    down = {i for i in range(js.get_numbuttons()) if js.get_button(i)}
    for i in sorted(down - prev):
        print(f"button {i} DOWN  ->  run the coach with --ptt-button {i}")
    prev = down
    time.sleep(0.02)
