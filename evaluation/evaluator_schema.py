"""Validated output from the seven-dimension speaker-script evaluator.

The evaluator model returns judgments only. Derived scores for GEPA are
computed separately in :mod:`evaluation.scoring`.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


RUBRIC_VERSION = "1.0.0"

DIMENSION_NAMES = (
    "grounding",
    "main_takeaway",
    "useful_context",
    "spoken_naturalness",
    "visual_reference",
    "cross_slide_connection",
    "coherence",
)

ALWAYS_APPLICABLE = (
    "grounding",
    "main_takeaway",
    "useful_context",
    "spoken_naturalness",
    "coherence",
)


class StrictResultModel(BaseModel):
    """Require every declared field and reject unexpected evaluator output."""

    model_config = ConfigDict(extra="forbid", strict=True)


class CriticalGroundingError(StrictResultModel):
    present: bool
    claims: list[str]

    @model_validator(mode="after")
    def explain_critical_error(self) -> "CriticalGroundingError":
        if self.present and not self.claims:
            raise ValueError("A critical grounding error must identify a claim")
        if not self.present and self.claims:
            raise ValueError("Claims must be empty when no critical grounding error is present")
        return self


class DimensionEvaluation(StrictResultModel):
    applicable: bool
    score: int | None = Field(ge=1, le=5)
    rationale: str
    evidence: list[str]
    problems: list[str]
    improvement: str

    @model_validator(mode="after")
    def match_score_to_applicability(self) -> "DimensionEvaluation":
        if self.applicable and self.score is None:
            raise ValueError("An applicable dimension requires a score")
        if not self.applicable and self.score is not None:
            raise ValueError("A non-applicable dimension must have score null")
        return self


class Dimensions(StrictResultModel):
    grounding: DimensionEvaluation
    main_takeaway: DimensionEvaluation
    useful_context: DimensionEvaluation
    spoken_naturalness: DimensionEvaluation
    visual_reference: DimensionEvaluation
    cross_slide_connection: DimensionEvaluation
    coherence: DimensionEvaluation

    @model_validator(mode="after")
    def require_core_dimensions(self) -> "Dimensions":
        for name in ALWAYS_APPLICABLE:
            if not getattr(self, name).applicable:
                raise ValueError(f"{name} must be applicable")
        return self


class EvaluationResult(StrictResultModel):
    rubric_version: Literal["1.0.0"]
    critical_grounding_error: CriticalGroundingError
    dimensions: Dimensions
