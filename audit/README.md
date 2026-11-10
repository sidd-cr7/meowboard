# MEOWBOARD system audit (not part of the normal test suite)

These tests drive the REAL Windows input system with `SendInput`, take keyboard focus with their own
window, and use Win+D / Alt+Tab. They must be run deliberately, on an interactive desktop, with nothing
important focused:

    .venv\Scripts\python.exe -m pytest audit -v -s

Normal `pytest tests` never touches the keyboard focus.
