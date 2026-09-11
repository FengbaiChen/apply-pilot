from .base import WorkdayStep


class ReviewStep(WorkdayStep):
    key = 'review'
    heading = 'Review'
    # The shared final audit runs on this step; navigation must stop here regardless
    # of whether the audit passes. There is deliberately no submit method.
