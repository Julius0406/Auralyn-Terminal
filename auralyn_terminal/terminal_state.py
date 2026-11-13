"""Small, independently testable foreground check used by the UI."""
import os
import termios


def is_readline_foreground(fd: int, shell_pid: int, ready: bool) -> bool:
    """Ready hook + foreground group + Readline-like terminal flags.

    ECHO is OFF in Readline as well as password prompts. Testing ECHO alone is
    therefore wrong; PS0 and canonical mode are essential additional gates.
    """
    if not ready or shell_pid <= 0:
        return False
    try:
        flags = termios.tcgetattr(fd)[3]
        return os.tcgetpgrp(fd) == shell_pid and not (flags & termios.ICANON) and not (flags & termios.ECHO)
    except (OSError, termios.error):
        return False


def suggestion_viewport_row(
    cursor_row: float,
    scroll_value: float,
    scroll_upper: float,
    scroll_page_size: float,
    visible_rows: float,
) -> float | None:
    """Locate the live prompt after screen clearing and scrollback reflow.

    VTE's cursor row is ABSOLUTE, and its vertical adjustment represents the
    visible viewport.  Normally subtracting the adjustment is enough.  After
    `clear` (notably `CSI 3 J`), VTE can briefly publish the new cursor row
    while the adjustment still contains the previous scrollback offset.  The
    old calculation hid the completion overlay permanently for that update.

    When the adjustment is at the live end, recover a bounded on-screen anchor.
    Never recover in the middle of manually-scrolled history: the prompt is
    truly off screen there and the popup must stay hidden.
    """
    if visible_rows <= 0:
        return None
    relative_row = cursor_row - scroll_value
    # Small fractions are possible when the GTK adjustment animates/reflows.
    if -0.75 <= relative_row < visible_rows:
        return max(0.0, min(visible_rows - 1, relative_row))
    at_live_end = scroll_value >= scroll_upper - scroll_page_size - 1.5
    if not at_live_end:
        # During CSI 3J the scroll value may already be reset to the start
        # while its upper limit still describes the old scrollback.  A cursor
        # actually on the first screen is visible in this specific state.
        at_new_top = scroll_value <= 1.5 and 0 <= cursor_row < visible_rows
        if not at_new_top:
            return None
    # A clear-to-top operation leaves the *visible* cursor on the first row.
    # Repeated `clear` calls can leave VTE's absolute cursor row far ahead of
    # its adjustment, even after the transient reflow. Clamping that
    # out-of-range difference to visible_rows-1 used to put the suggestion
    # popup at the BOTTOM while Bash's prompt was at the TOP. Do not guess
    # 'bottom': use the top-of-screen anchor until VTE's normal coordinates
    # are again self-consistent. We still decline to draw in scrollback above.
    if 0 <= cursor_row < visible_rows:
        return cursor_row
    return 0.0
