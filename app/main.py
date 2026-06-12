from fastapi import FastAPI, Response

GREETING = "Hello from WatchingYou-server"

app = FastAPI(title="WatchingYou Server")


@app.get("/health", response_class=Response)
def health() -> Response:
    return Response(content=GREETING, media_type="text/plain")


@app.post("/chat", response_class=Response)
def chat() -> Response:
    return Response(content=GREETING, media_type="text/plain")
