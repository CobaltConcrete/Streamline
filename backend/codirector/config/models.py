"""Config file schemas — build spec v1.0 §4.5. Secrets (OBS password, Twitch
tokens) are never modeled here: they are read from the OS keyring at adapter
construction time, per D-14/R-SAF-08."""
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class OBSConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 4455


class TwitchConfig(BaseModel):
    channel: str


class ASRConfig(BaseModel):
    provider: Literal["parakeet", "mock"] = "parakeet"
    model: str = "nvidia/parakeet-unified-en-0.6b"
    device: Literal["cuda"] = "cuda"  # cpu is not a supported configuration (D-7)
    streaming_latency_ms: int = 160
    sample_rate: int = 16000
    min_free_vram_mb: int = 2500


class ReasoningConfig(BaseModel):
    provider: Literal["auto", "opencode", "openrouter", "anthropic", "openai", "http", "mock"] = "auto"
    endpoint: str = ""
    model: str = "deepseek-v4-flash-free"
    fallback_models: list[str] = Field(default_factory=lambda: [
        "longcat-2.0-free",
        "ling-3.0-tiny-free",
        "mimo-v2.5-free",
        "laguna-s-2.1-free",
        "nemotron-3-ultra-free",
    ])
    structured_output_mode: Literal["attribute", "system_prompt"] = "attribute"
    timeout_s: float = 45.0
    max_attempts: int = Field(default=3, ge=1)


class PipelineConfig(BaseModel):
    chat_batch_max_representative_texts: int = Field(default=50, ge=1)
    chat_batch_max_wait_s: float = Field(default=10.0, gt=0)
    chat_filter_min_recognized_words: int = Field(default=3, ge=1)
    rolling_window_s: int = 90
    decision_ttl_s: int = 20


class AutonomyConfig(BaseModel):
    startup_level: Literal["OBSERVE"] = "OBSERVE"  # R-AUT-01: this is the only legal value


class AppConfig(BaseModel):
    obs: OBSConfig = Field(default_factory=OBSConfig)
    twitch: TwitchConfig
    asr: ASRConfig = Field(default_factory=ASRConfig)
    reasoning: ReasoningConfig = Field(default_factory=ReasoningConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    autonomy: AutonomyConfig = Field(default_factory=AutonomyConfig)
    environment: Literal["development", "production"] = "development"


class PersonaThresholds(BaseModel):
    surface_min_score: float = Field(ge=0.0, le=1.0)
    max_queue_items: int = 3
    max_prompts_per_minute: int = 2


class PersonaWeights(BaseModel):
    relevance: float
    breadth: float
    novelty: float
    urgency: float
    support_tier: float


class PersonaConfig(BaseModel):
    name: str
    weights: PersonaWeights
    thresholds: PersonaThresholds
    banned_topics: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "PersonaConfig":
        # R-CFG-01: persona weights failing to sum to 1.0 refuse to load.
        total = (
            self.weights.relevance
            + self.weights.breadth
            + self.weights.novelty
            + self.weights.urgency
            + self.weights.support_tier
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"persona weights must sum to 1.0, got {total}")
        return self
