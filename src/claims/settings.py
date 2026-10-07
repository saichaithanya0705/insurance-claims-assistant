from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True, env_ignore_empty=True
    )
    synapt_mode: Literal["fixture", "live"] = "fixture"
    synapt_mcp_url: str = "https://synapt.example.com/tristore/mcp/"
    synapt_auth_base: str = "https://synapt.example.com/auth_service/api/v1/auth/token"
    synapt_username: str = ""
    synapt_password: SecretStr = SecretStr("")
    synapt_provider_id: str = ""
    synapt_top_k: int = Field(default=5, ge=1, le=20)
    # How many chunks of ingested historical claim cards to request for semantic matching.
    synapt_case_top_k: int = Field(default=20, ge=1, le=50)
    synapt_graph_hops: int = Field(default=2, ge=0, le=4)
    # Also call trident_get_procedures / trident_search. Their output is uncitable (no source IDs).
    synapt_graph_enrichment: bool = False
    synapt_auth_encoding: Literal["json", "form"] = "json"
    synapt_auth_username_field: Literal["username", "email"] = "username"
    synapt_timeout_seconds: float = Field(default=20, ge=1, le=120)
    claims_database_path: Path = Path("data/runtime/claims.sqlite")
    claims_auth_enabled: bool = True
    claims_auth_database_path: Path | None = None
    claims_data_path: Path = Path("data/raw/claims_sample.json")
    # Full 100M-row dataset (Parquet), queried in place by DuckDB when present.
    claims_parquet_path: Path = Path("data/raw/parquet/insurance_claims_100M.parquet")
    claims_train_rows: int = Field(default=600_000, ge=1_000, le=5_000_000)
    claims_candidate_limit: int = Field(default=300, ge=20, le=2_000)
    claims_duckdb_memory: str = Field(default="3GB", pattern=r"^\d+(\.\d+)?(MB|GB)$")
    claims_artifact_dir: Path = Path("artifacts/models")
    claims_search_enabled: bool = True
    claims_search_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    claims_search_cache_dir: Path = Path("artifacts/search-model")
    claims_search_min_similarity: float = Field(default=0.34, ge=0, le=1)
    agent_mode: Literal["fixture", "live"] = "fixture"
    llm_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_api_key: SecretStr = SecretStr("")
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "nvidia/nemotron-3-super-120b-a12b"
    llm_timeout_seconds: float = Field(default=60, ge=1, le=120)
    llm_max_tokens: int = Field(default=4096, ge=128, le=16384)
    llm_enable_thinking: bool = False
    claims_api_key: SecretStr = SecretStr("")
    deepeval_model: str = ""
    # Independent LLM judge. Empty falls back to DEEPEVAL_MODEL, then LLM_MODEL (not independent).
    judge_model: str = ""
    judge_mode: Literal["off", "inline"] = "off"
    # The judge is advisory and runs in the background, so it cannot stall a brief. Each of its two
    # attempts gets 60 s: with 35 s, about a quarter of live verdicts failed on endpoint latency.
    judge_timeout_seconds: float = Field(default=60, ge=5, le=120)

    @model_validator(mode="after")
    def validate_live(self):
        endpoint = urlsplit(self.llm_base_url)
        if (
            endpoint.hostname == "integrate.api.nvidia.com"
            and not self.llm_api_key.get_secret_value()
        ):
            self.llm_api_key = self.nvidia_api_key
        if self.agent_mode == "live":
            if not self.llm_api_key.get_secret_value() or not self.llm_model:
                raise ValueError(
                    "Live agents require NVIDIA_API_KEY for NVIDIA, or LLM_API_KEY for another endpoint, plus LLM_MODEL"
                )
            if (
                endpoint.scheme != "https"
                or not endpoint.hostname
                or endpoint.username
                or endpoint.password
                or endpoint.query
                or endpoint.fragment
            ):
                raise ValueError("Live model endpoint must use HTTPS without embedded credentials")
        if self.synapt_mode == "live":
            if not all(
                (
                    self.synapt_username,
                    self.synapt_password.get_secret_value(),
                    self.synapt_provider_id,
                )
            ):
                raise ValueError("Live Synapt requires username, password and provider ID")
            if not self.synapt_mcp_url.startswith("https://"):
                raise ValueError("Live Synapt MCP must use HTTPS")
            if not self.synapt_auth_base.startswith("https://"):
                raise ValueError("Live Synapt auth must use HTTPS")
        return self
