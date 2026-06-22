import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from dotenv import load_dotenv

from routers.post_router import router as post_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
)
logger = logging.getLogger("main")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing — add it to your .env file.")

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Gemini Social Post Engine",
    description="Designer-level social media post generation pipeline.",
    version="2.0.0",
)

# ---------------------------------------------------------------------------
# CORS  — reads origins from .env, never hardcoded wildcard
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Gemini client — created once, shared via app.state
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    app.state.gemini_client = genai.Client(api_key=API_KEY)
    logger.info("Gemini client initialised.")


@app.on_event("shutdown")
async def shutdown():
    logger.info("Application shutting down.")

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "version": app.version}


@app.get("/api/list-models", tags=["Health"])
def list_models():
    models = [m.name for m in app.state.gemini_client.models.list()]
    return {"available_models": models}


# Mount the post generation router
app.include_router(post_router)