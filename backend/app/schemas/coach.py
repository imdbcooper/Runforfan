from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationCreate(StrictModel):
    surface: Literal["overview"]


class CoachTurnCreate(StrictModel):
    message: Annotated[str, Field(min_length=1, max_length=4000)]
    context: Literal["general", "pre_workout", "post_workout", "missed_workout", "weekly_review"]

    @field_validator("message")
    @classmethod
    def message_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be blank")
        return value


class Citation(StrictModel):
    source_key: Annotated[str, Field(min_length=1, max_length=128)]


class ReadinessActionPreviewRequest(StrictModel):
    kind: Literal["readiness_action"]
    action: Literal["shorten_easy", "easy_replacement"]


class CoachActionPreviewRequest(StrictModel):
    kind: Literal["coach_action"]
    workout_id: int
    action: Literal["skip", "reschedule"]
    reason: Literal["schedule_conflict", "fatigue", "illness", "pain", "weather", "other"]
    target_date: date | None = None

    @model_validator(mode="after")
    def target_date_matches_action(self):
        if (self.action == "reschedule") != (self.target_date is not None):
            raise ValueError("target_date is required only for reschedule")
        return self


class WeeklyStrategyPreviewRequest(StrictModel):
    kind: Literal["weekly_strategy"]
    review_id: int
    strategy: Literal["hold", "deload", "resume", "conservative_progression"]


PreviewRequest = Annotated[
    ReadinessActionPreviewRequest | CoachActionPreviewRequest | WeeklyStrategyPreviewRequest,
    Field(discriminator="kind"),
]


class MemoryUpdate(StrictModel):
    communication_style: Literal["brief", "detailed"] | None = None
    coaching_focus: Literal["consistency", "race_goal", "recovery", "general"] | None = None
    confirmed_available_days: list[Annotated[int, Field(ge=0, le=6)]] | None = None
    source_message_id: int | None = None

    @model_validator(mode="after")
    def require_value_and_unique_days(self):
        if self.communication_style is None and self.coaching_focus is None and self.confirmed_available_days is None:
            raise ValueError("at least one memory value is required")
        if self.confirmed_available_days is not None and len(set(self.confirmed_available_days)) != len(self.confirmed_available_days):
            raise ValueError("confirmed_available_days must be unique")
        return self


class Clarification(StrictModel):
    id: Annotated[str, Field(min_length=1, max_length=64)]
    question: Annotated[str, Field(min_length=1, max_length=600)]
    options: Annotated[list[Annotated[str, Field(min_length=1, max_length=120)]], Field(default_factory=list, max_length=6)]


class ProviderCoachOutput(StrictModel):
    intent: Literal["explain_decision", "ask_clarification", "request_preview", "inform"]
    answer: Annotated[str, Field(min_length=1, max_length=6000)]
    citations: Annotated[list[Citation], Field(default_factory=list, max_length=8)]
    safety_status: Literal["normal", "caution", "medical_boundary"]
    clarification: Clarification | None = None
    preview_request: PreviewRequest | None = None
    memory_candidate: MemoryUpdate | None = None

    @model_validator(mode="after")
    def handoff_matches_intent(self):
        if not self.citations:
            raise ValueError("at least one citation is required")
        if self.memory_candidate is not None and self.memory_candidate.source_message_id is not None:
            raise ValueError("provider memory candidates cannot set source_message_id")
        if self.clarification is not None and self.preview_request is not None:
            raise ValueError("clarification and preview_request are mutually exclusive")
        if self.intent == "ask_clarification" and self.clarification is None:
            raise ValueError("ask_clarification requires clarification")
        if self.intent == "request_preview" and self.preview_request is None:
            raise ValueError("request_preview requires preview_request")
        if self.intent not in {"ask_clarification", "request_preview"} and (self.clarification or self.preview_request):
            raise ValueError("handoff is not allowed for this intent")
        return self


class CoachAssistantResponse(StrictModel):
    output: ProviderCoachOutput
    mode: Literal["llm", "deterministic_fallback"]
    provider: str | None = None
    provider_model: str | None = None
    attempt_count: Annotated[int, Field(ge=0)]
    authoritative_safety_status: Literal["normal", "caution", "medical_boundary"]


class PreviewCreate(StrictModel):
    assistant_message_id: int


class MessageOut(StrictModel):
    id: int
    role: str
    content: str | None
    created_at: datetime | None
    response: CoachAssistantResponse | None = None


class ConversationOut(StrictModel):
    id: str
    status: str
    title: str | None
    created_at: datetime | None
    updated_at: datetime | None
    messages: list[MessageOut] | None = None
