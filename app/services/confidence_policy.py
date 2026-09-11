from enum import StrEnum


class ConfidencePolicy:
    """Compatibility shim; Workday now uses explicit answer states, not thresholds."""
    def __init__(self, auto_fill_threshold=0.9, human_threshold=0.7):
        if human_threshold >= auto_fill_threshold:
            raise ValueError("human_threshold must be below auto_fill_threshold")
        self.auto_fill_threshold = auto_fill_threshold
        self.human_threshold = human_threshold

    def classify(self, confidence):
        if confidence >= self.auto_fill_threshold: return _Action.AUTO_FILL
        if confidence >= self.human_threshold: return _Action.FILL_AND_REVIEW
        return _Action.REQUIRE_HUMAN


class _Action(StrEnum):
    AUTO_FILL = "AUTO_FILL"
    FILL_AND_REVIEW = "FILL_AND_REVIEW"
    REQUIRE_HUMAN = "REQUIRE_HUMAN"
