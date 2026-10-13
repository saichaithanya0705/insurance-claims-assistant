"""Download the public search model once; runtime search uses local files only."""

from fastembed import TextEmbedding

from claims.core.settings import Settings

settings = Settings()
model = TextEmbedding(
    model_name=settings.claims_search_model,
    cache_dir=str(settings.claims_search_cache_dir),
    threads=2,
)
vector = next(model.embed(["Search readiness check"]))
print(f"Local case search ready: {settings.claims_search_model}, {len(vector)} dimensions")
