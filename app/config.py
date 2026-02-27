from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    base_url: str = "http://localhost:8000"
    whisper_model: str = "base"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    max_concurrent_jobs: int = 2
    max_duration_seconds: int = 7200
    db_path: str = "data/ytqueue.db"
    audio_dir: str = "data/audio"
    temp_dir: str = "/tmp/ytqueue"
    job_ttl_seconds: int = 3600
    # LLM
    llm_provider: str = "none"          # none | anthropic | openai | ollama
    llm_model: str = ""                 # e.g. claude-haiku-4-5-20251001 / gpt-4o-mini
    llm_api_key: str = ""
    llm_base_url: str = ""              # For Ollama or custom endpoints
    summary_max_words: int = 80

    model_config = SettingsConfigDict(env_prefix="YTQUEUE_")


settings = Settings()
