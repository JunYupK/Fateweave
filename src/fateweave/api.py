from fastapi import FastAPI

app = FastAPI(title="Fateweave")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "fateweave"}
