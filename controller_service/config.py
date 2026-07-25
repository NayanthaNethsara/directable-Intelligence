"""Central runtime configuration.

Everything tunable lives here and is overridable via environment variables
or a `.env` file at the repo root (see `.env.example`). Code should import
`settings` rather than reading os.environ directly, so there is exactly one
place where configuration enters the process.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # OpenAI-compatible LLM backend (llama.cpp / Ollama / LM Studio / vLLM...)
    llm_base_url: str = "http://localhost:8080/v1"
    llm_api_key: str = "local"
    llm_model: str = "qwen3-0.6b"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 64
    llm_timeout_s: float = 30.0

    default_brain: str = "heuristic"
    log_dir: Path = Path("logs")
    skills_file: Path = Path(__file__).parent / "skills.json"


settings = Settings()
