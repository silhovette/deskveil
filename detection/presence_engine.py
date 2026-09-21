"""Pure state machine: only successful, consecutive samples prove presence/absence."""
from enum import Enum, auto
from math import hypot, isfinite
import config


class State(Enum):
    PRESENT = auto()
    PENDING_AWAY = auto()
    COVERED = auto()
    PENDING_RETURN = auto()
    SNOOZED = auto()


def owner_candidate(boxes):
    """A seating-position heuristic, deliberately NOT identity verification."""
    for x1, y1, x2, y2 in boxes:
        if not all(isfinite(v) for v in (x1, y1, x2, y2)):
            continue
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            continue
        area = (x2 - x1) * (y2 - y1)
        distance = hypot((x1 + x2) / 2 - .5, (y1 + y2) / 2 - .5)
        if area >= config.MIN_RETURN_FACE_RATIO and distance <= config.MAX_RETURN_CENTER_DISTANCE:
            return True
    return False


class PresenceEngine:
    def __init__(self, away_time=config.AWAY_CONFIRM_TIME,
                 return_time=config.RETURN_CONFIRM_TIME, max_gap=config.MAX_SAMPLE_GAP):
        self.away_time, self.return_time, self.max_gap = away_time, return_time, max_gap
        self.state = State.PRESENT
        self.snoozed_until = None
        self.since = self.last_sample = None
        self.manual_wait_for_absence = False

    @property
    def covered(self):
        return self.state in (State.COVERED, State.PENDING_RETURN)

    def interrupt(self):
        """Unknown data cancels evidence, but never reveals an existing cover."""
        if self.state == State.PENDING_AWAY:
            self.state = State.PRESENT
        elif self.state == State.PENDING_RETURN:
            self.state = State.COVERED
        self.since = self.last_sample = None
        return self.state

    def resume(self):
        self.state = State.PRESENT
        self.since = self.last_sample = self.snoozed_until = None
        self.manual_wait_for_absence = False

    def snooze(self, now, seconds=600):
        self.resume()
        self.state = State.SNOOZED
        self.snoozed_until = now + seconds

    def cover_now(self):
        self.resume()
        self.state = State.COVERED
        self.manual_wait_for_absence = True

    def tick(self, now):
        """Clock alone can expire snooze or invalidate samples, never auto-cover."""
        if self.state == State.SNOOZED and now >= self.snoozed_until:
            self.resume()
        if self.last_sample is not None and now - self.last_sample > self.max_gap:
            self.interrupt()
        return self.state

    def update(self, present, now):
        self.tick(now)
        if self.state == State.SNOOZED:
            return self.state
        if present is None:
            return self.interrupt()
        if self.last_sample is not None and now <= self.last_sample:
            return self.interrupt()
        self.last_sample = now
        if self.manual_wait_for_absence:
            if not present:
                self.manual_wait_for_absence = False
            return self.state
        if self.state == State.PRESENT and not present:
            self.state, self.since = State.PENDING_AWAY, now
        elif self.state == State.PENDING_AWAY:
            if present:
                self.state, self.since = State.PRESENT, None
            elif now - self.since + 1e-9 >= self.away_time:
                self.state, self.since = State.COVERED, None
        elif self.state == State.COVERED and present:
            self.state, self.since = State.PENDING_RETURN, now
        elif self.state == State.PENDING_RETURN:
            if not present:
                self.state, self.since = State.COVERED, None
            elif now - self.since + 1e-9 >= self.return_time:
                self.state, self.since = State.PRESENT, None
        return self.state
