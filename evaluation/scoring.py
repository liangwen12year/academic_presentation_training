"""Deterministic, per-example score passed to GEPA.

The scalar is an initial policy for optimization, not an empirical claim that
the seven rubric dimensions have equal importance.
"""

from evaluation.evaluator_schema import DIMENSION_NAMES, EvaluationResult


def calculate_score(evaluation: EvaluationResult) -> float:
    """Return a 0–1 score, with a critical grounding error scored at zero.

    Each applicable dimension contributes its 1–5 score equally. Optional
    dimensions are omitted only when the evaluator marked them non-applicable.
    A failing example is retained with a score of zero and diagnostic feedback.
    """

    if evaluation.critical_grounding_error.present:
        return 0.0

    scores = [
        dimension.score
        for name in DIMENSION_NAMES
        if (dimension := getattr(evaluation.dimensions, name)).applicable
        and dimension.score is not None
    ]
    # The schema requires five always-applicable dimensions.
    return sum(scores) / (5 * len(scores))
