from fastapi import FastAPI

app = FastAPI(title="ClearTerms")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
