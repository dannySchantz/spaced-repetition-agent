from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value):
    if value.tzinfo is None:
        raise ValueError("UTC timestamp required")
    return value.astimezone(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CardInput(StrictModel):
    term: str = Field(min_length=1, max_length=2000)
    definition: str = Field(min_length=1, max_length=20000)
    context: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    rubric: list[str] = Field(default_factory=list, max_length=20)
    approved: bool = True
    provenance: str = "user"
    sms_label: str | None = Field(default=None, max_length=500)

    @field_validator("term", "definition")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Cannot be blank")
        return value.strip()


class EditInput(CardInput):
    expected_revision: str
    reset_learning: bool = False


class SessionInput(StrictModel):
    request_key: str = Field(min_length=1, max_length=200)
    count: int = Field(default=10, ge=1, le=100)
    channel: Literal["tui", "sms"] = "tui"


class RatingInput(StrictModel):
    rating: int = Field(ge=1, le=4)
    expected_version: int = Field(ge=0)
    request_key: str = Field(min_length=1, max_length=200)


class CorrectionInput(RatingInput):
    reason: str = Field(min_length=1, max_length=1000)


class Settings(StrictModel):
    timezone: str = "America/New_York"
    slots: list[str] = Field(default=["12:00", "18:00"], max_length=8)
    quiet_start: str = "21:00"
    quiet_end: str = "09:00"
    batch_size: int = Field(default=3, ge=1, le=10)
    new_per_day: int = Field(default=3, ge=0, le=100)
    daily_prompts: int = Field(default=20, ge=0, le=200)
    paused: bool = True
    opted_in: bool = False
    provider_opted_out: bool = False
    reduced_motion: bool = False
    retention: float = Field(default=0.9, ge=0.7, le=0.99)
    policy_generation: int = 1
    monthly_segments: int = Field(default=1000, ge=0, le=100000)
    sleep_start: str = "22:00"
    wake_time: str = "07:00"
    message_window_start: str = "08:00"
    message_window_end: str = "20:00"
    onboarding_complete: bool = False

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, v):
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError:
            raise ValueError("Unknown IANA timezone") from None
        return v

    @field_validator(
        "quiet_start",
        "quiet_end",
        "sleep_start",
        "wake_time",
        "message_window_start",
        "message_window_end",
    )
    @classmethod
    def valid_time(cls, v):
        datetime.strptime(v, "%H:%M")
        if len(v) != 5:
            raise ValueError("Use HH:MM")
        return v

    @field_validator("slots")
    @classmethod
    def valid_slots(cls, v):
        for slot in v:
            cls.valid_time(slot)
        return sorted(set(v))
