from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"), extra="ignore", populate_by_name=True, env_ignore_empty=True
    )
    # Synapt is the knowledge layer and is always required. There is no mode that runs without it.
    synapt_mode: Literal["live"] = "live"
    synapt_mcp_url: str = "https://synapt.example.com/tristore/mcp/"
    synapt_auth_base: str = "https://synapt.example.com/auth_service/api/v1/auth/token"
    synapt_username: str = ""
    synapt_password: SecretStr = SecretStr("")
    synapt_provider_id: str = ""
    synapt_top_k: int = Field(default=5, ge=1, le=20)
    # At most this many similar past claims from Synapt's ticket store are kept for semantic matching.
    synapt_case_top_k: int = Field(default=20, ge=1, le=50)
    # Sent only to a tool that declares `graph_hops` (trident_query). trident_get_chunks does not, so this has no effect
    # on passage retrieval; the knowledge-graph lookup (claims.synapt.knowledge_graph) walks to a fixed depth of 2.
    synapt_graph_hops: int = Field(default=2, ge=0, le=4)
    # Legacy: also fold raw trident_get_procedures / trident_search output into the passage evidence. That output has
    # no source IDs and stays off. The cited, source-linked graph lookup (claims.synapt.knowledge_graph) is separate and always on.
    synapt_graph_enrichment: bool = False
    # The client IDs Synapt's Agent Connector issues, one per agent that reads the knowledge base (only these three agents call
    # Synapt). The ID names an agent so Synapt can track it; the application records that one is set, and does not yet
    # authenticate with it (see docs/AGENTS.md).
    synapt_agent_passage_retriever_client_id: str = ""
    synapt_agent_graph_navigator_client_id: str = ""
    synapt_agent_knowledge_qa_client_id: str = ""
    synapt_auth_encoding: Literal["json", "form"] = "json"
    synapt_auth_username_field: Literal["username", "email"] = "username"
    synapt_timeout_seconds: float = Field(default=20, ge=1, le=120)
    # One attempt at the passage search, or at the graph lookup (about a dozen calls). Healthy attempts take 1.5 to 7 s. Measured on
    # 12 October, about 2% of the calls inside them stall for about 18 s and then succeed at once on a retry, so waiting out the
    # 20 s timeout (and then the session's own clean-up) costs 20 to 40 s for nothing.
    synapt_fast_attempt_seconds: float = Field(default=12, ge=1, le=60)
    claims_database_path: Path = Path("data/runtime/claims.sqlite")
    claims_auth_enabled: bool = True
    claims_auth_database_path: Path | None = None
    claims_data_path: Path = Path("data/raw/claims_sample.json")
    # Full 100M-row dataset (Parquet), queried in place by DuckDB when present.
    claims_parquet_path: Path = Path("data/raw/parquet/insurance_claims_100M.parquet")
    # Built by scripts/build_cohort_summary.py; used only if it belongs to the dataset in use, otherwise the scan runs as before.
    claims_cohort_summary_path: Path | None = Path("data/derived/cohort_summary.duckdb")
    # Built by scripts/build_claims_copy.py (about 5 minutes, 2.6 GB): the dataset in DuckDB's own format, sorted, which makes the search for
    # the closest claims about twice as fast. Used only if it belongs to the dataset in use; otherwise the Parquet file is searched.
    claims_sorted_copy_path: Path | None = Path("data/derived/claims_sorted.duckdb")
    claims_train_rows: int = Field(default=600_000, ge=1_000, le=5_000_000)
    claims_candidate_limit: int = Field(default=300, ge=20, le=2_000)
    claims_duckdb_memory: str = Field(default="3GB", pattern=r"^\d+(\.\d+)?(MB|GB)$")
    claims_artifact_dir: Path = Path("artifacts/models")
    claims_search_enabled: bool = True
    # Degraded mode: used only after a live Synapt call fails (see claims.retrieval.fallback). It needs the local
    # card file written by scripts/build_profile_corpus.py; without it a Synapt failure fails the run.
    claims_fallback_enabled: bool = True
    claims_fallback_cards_path: Path = Path(
        "artifacts/synapt/corpus-profile-balanced-2026-10-09/claim_cards.parquet"
    )
    claims_fallback_index_dir: Path = Path("artifacts/synapt/fallback-index")
    claims_search_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    claims_search_cache_dir: Path = Path("artifacts/search-model")
    claims_search_min_similarity: float = Field(default=0.34, ge=0, le=1)
    agent_mode: Literal["fixture", "live"] = "fixture"
    llm_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_api_key: SecretStr = SecretStr("")
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = "nvidia/nemotron-3-super-120b-a12b"
    # How long one model call may take. A slow model (GLM 5.3 flash on NVIDIA NIM takes 25 s for a 100-token answer) needs more.
    llm_timeout_seconds: float = Field(default=60, ge=1, le=900)
    # The intake reader runs while a person waits for the form to fill, so it has its own, shorter limit.
    intake_timeout_seconds: float = Field(default=25, ge=5, le=900)
    # How many model requests a minute this application may make (0 means no limit). The provider limits a key; when a stream of
    # investigations goes over it every call fails with HTTP 429, the brief's own included. The brief's calls wait for a slot; an
    # agent's optional follow-up calls are skipped once only the reserve is left (claims.llm.ratelimit).
    llm_requests_per_minute: int = Field(default=36, ge=0, le=600)
    llm_optional_reserve: int = Field(default=10, ge=0, le=300)
    llm_max_tokens: int = Field(default=4096, ge=128, le=16384)
    llm_enable_thinking: bool = False
    # One model per role when they differ (empty means LLM_MODEL): short structured calls can use a small fast model while the
    # investigation's findings use a larger one. Used by the OpenAI-compatible provider; the Anthropic provider has its own set below.
    llm_model_classification: str = ""
    llm_model_investigation: str = ""
    llm_model_recommendation: str = ""
    llm_model_intake: str = ""
    # The model the retrieval agents use to decide their follow-up searches (empty means LLM_MODEL).
    llm_model_retrieval: str = ""
    # The model the Supervisor agent uses (empty means LLM_MODEL).
    llm_model_supervision: str = ""
    # Whether the Supervisor reviews each finished brief, writes the handler summary and may send it back once to be fixed.
    agent_supervisor: bool = True
    # How long the Supervisor's own model call may take (a revision's calls use the usual model timeouts).
    agent_supervisor_seconds: float = Field(default=25, ge=3, le=300)
    # Whether the agents that read the knowledge base let a model decide on follow-up searches after their standard ones. The
    # standard searches always run; with this off, or when the model step fails, the result is exactly what they alone found.
    agent_llm_retrieval: bool = True
    # The most model calls one tool-using agent may make: one to look around (searching), one to choose.
    agent_tool_rounds: int = Field(default=2, ge=1, le=5)
    # The whole time a model may spend on one agent's follow-up. When it runs out the standard result stands: one slow model call
    # (a 29 s call was seen on 12 October) must not hold up an investigation.
    agent_followup_seconds: float = Field(default=8, ge=2, le=300)
    # Models that, like Nemotron 3, accept chat_template_kwargs.enable_thinking: the request sets it from LLM_ENABLE_THINKING
    # (off by default) so a reasoning model does not spend seconds thinking before a short structured answer.
    llm_thinking_switch_prefixes: str = "nvidia/nemotron-3,nvidia/nemotron-nano-3"
    # Which service writes the brief (classification, investigation, recommendation) and reads the intake notes. The judge and the
    # DeepEval model use their own setting below, so the writer and its reviewer can come from different providers.
    llm_provider: Literal["openai_compatible", "anthropic"] = "openai_compatible"
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_version: str = "2023-06-01"
    anthropic_model: str = "claude-sonnet-5-5"
    # One model per role when they differ (empty means ANTHROPIC_MODEL): a small fast model for the short structured calls and a
    # larger one for the investigation's findings, for example.
    anthropic_model_classification: str = ""
    anthropic_model_investigation: str = ""
    anthropic_model_recommendation: str = ""
    anthropic_model_intake: str = ""
    claims_api_key: SecretStr = SecretStr("")
    deepeval_model: str = ""
    # Independent LLM judge. Empty falls back to DEEPEVAL_MODEL, then LLM_MODEL (not independent).
    judge_model: str = ""
    judge_provider: Literal["openai_compatible", "anthropic"] = "openai_compatible"
    judge_mode: Literal["off", "inline"] = "off"
    # The judge is advisory and runs in the background, so it cannot stall a brief. Each of its two
    # attempts gets 60 s: with 35 s, about a quarter of live verdicts failed on endpoint latency.
    judge_timeout_seconds: float = Field(default=60, ge=5, le=900)

    @field_validator("synapt_mode", mode="before")
    @classmethod
    def synapt_cannot_be_disabled(cls, value):
        if value != "live":
            raise ValueError(
                "Synapt cannot be disabled: SYNAPT_MODE must be 'live'. "
                "There is no fixture or fallback mode."
            )
        return value

    def agent_client_id(self, agent_id: str) -> str:
        """The Agent Connector client ID set for an agent, or an empty string."""
        return getattr(self, f"synapt_agent_{agent_id}_client_id", "")

    def model_for(self, purpose: str, provider: str | None = None) -> str:
        """The model that does ``purpose`` (classification, investigation, recommendation, intake) for ``provider``."""
        if (provider or self.llm_provider) != "anthropic":
            return {
                "classification": self.llm_model_classification,
                "investigation": self.llm_model_investigation,
                "recommendation": self.llm_model_recommendation,
                "intake": self.llm_model_intake,
                "retrieval": self.llm_model_retrieval,
                "supervision": self.llm_model_supervision,
            }.get(purpose, "") or self.llm_model
        specific = {
            "classification": self.anthropic_model_classification,
            "investigation": self.anthropic_model_investigation,
            "recommendation": self.anthropic_model_recommendation,
            "intake": self.anthropic_model_intake,
        }.get(purpose, "")
        return specific or self.anthropic_model

    def writer_models(self) -> set[str]:
        """Every model that can write or read-in what the judge reviews."""
        if self.llm_provider != "anthropic":
            return {
                self.llm_model, self.llm_model_classification, self.llm_model_investigation,
                self.llm_model_recommendation, self.llm_model_intake, self.llm_model_retrieval, self.llm_model_supervision,
            } - {""}
        return {
            self.anthropic_model, self.anthropic_model_classification, self.anthropic_model_investigation,
            self.anthropic_model_recommendation, self.anthropic_model_intake,
        } - {""}

    @model_validator(mode="after")
    def validate_live(self):
        endpoint = urlsplit(self.llm_base_url)
        if (
            endpoint.hostname == "integrate.api.nvidia.com"
            and not self.llm_api_key.get_secret_value()
        ):
            self.llm_api_key = self.nvidia_api_key
        if self.agent_mode == "live" and "anthropic" in (self.llm_provider, self.judge_provider):
            claude = urlsplit(self.anthropic_base_url)
            if not self.anthropic_api_key.get_secret_value():
                raise ValueError("The Anthropic provider needs ANTHROPIC_API_KEY (put it in .env.local, which git ignores)")
            if claude.scheme != "https" or not claude.hostname or claude.username or claude.password or claude.query or claude.fragment:
                raise ValueError("The Anthropic endpoint must use HTTPS without embedded credentials")
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
        if not all(
            (
                self.synapt_username,
                self.synapt_password.get_secret_value(),
                self.synapt_provider_id,
            )
        ):
            raise ValueError(
                "Synapt is required: set SYNAPT_USERNAME, SYNAPT_PASSWORD and SYNAPT_PROVIDER_ID "
                "(see docs/SETUP.md). The application does not run without it."
            )
        if not self.synapt_mcp_url.startswith("https://"):
            raise ValueError("Synapt MCP must use HTTPS")
        if not self.synapt_auth_base.startswith("https://"):
            raise ValueError("Synapt auth must use HTTPS")
        return self
