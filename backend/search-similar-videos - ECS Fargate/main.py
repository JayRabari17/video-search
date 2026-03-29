from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import json
import boto3
import os
import logging
import base64
import uuid
import datetime
import asyncio
import math
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth
from typing import List, Dict, Optional, Any
from pydantic import BaseModel
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt  
from pymongo import MongoClient  
from pymongo.errors import PyMongoError  
from passlib.context import CryptContext  
from dotenv import load_dotenv

load_dotenv()


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(name=__name__)


_enable_docs = True # os.environ.get("ENABLE_DOCS", "true").strip().lower() in {"1", "true", "yes", "y", "on"}
app = FastAPI(
    title="Video Search Service",
    version="1.0.0",
    docs_url="/docs" if _enable_docs else None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Auth (JWT + DocumentDB)
# =========================
JWT_SECRET = (os.environ.get("JWT_SECRET") or "").strip()
JWT_ISSUER = (os.environ.get("JWT_ISSUER") or "video-search").strip()
JWT_AUDIENCE = (os.environ.get("JWT_AUDIENCE") or "video-search-ui").strip()
DOCDB_AUTH_TIMEOUT_SECONDS = int(os.environ.get("DOCDB_AUTH_TIMEOUT_SECONDS", "8"))
_DOCDB_DEFAULT_DB = "video_search"
_DOCDB_DEFAULT_USERS_COLLECTION = "users"
AUTH_DEV_MODE = os.environ.get("AUTH_DEV_MODE", "false").strip().lower() in {"1", "true", "yes", "y", "on"}
AUTH_DEV_USERNAME = (os.environ.get("AUTH_DEV_USERNAME") or "").strip()
AUTH_DEV_PASSWORD = (os.environ.get("AUTH_DEV_PASSWORD") or "").strip()
AUTH_DEV_EMAIL = (os.environ.get("AUTH_DEV_EMAIL") or "").strip()
_bearer = HTTPBearer(auto_error=False)
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_docdb_client: Optional[MongoClient] = None
_docdb_client_uri: Optional[str] = None


def get_docdb_settings() -> tuple:
    uri = (os.environ.get("DOCDB_URI") or "").strip()
    if not uri:
        raise HTTPException(status_code=500, detail="DocumentDB not configured (DOCDB_URI missing)")
    db = (os.environ.get("DOCDB_DB") or _DOCDB_DEFAULT_DB).strip() or _DOCDB_DEFAULT_DB
    users_collection = (
        (os.environ.get("DOCDB_USERS_COLLECTION") or _DOCDB_DEFAULT_USERS_COLLECTION).strip()
        or _DOCDB_DEFAULT_USERS_COLLECTION
    )
    return uri, db, users_collection


def get_docdb_client() -> MongoClient:
    global _docdb_client, _docdb_client_uri
    uri, _, _ = get_docdb_settings()
    if _docdb_client is not None and _docdb_client_uri == uri:
        return _docdb_client
    _docdb_client_uri = uri
    
    # Use TLS certificate bundle for DocumentDB
    # In Docker container, certificate is at /app/global-bundle.pem
    # For local development, you can download it or use tlsInsecure=true
    import os
    tls_ca_file = "/app/global-bundle.pem" if os.path.exists("/app/global-bundle.pem") else None
    
    _docdb_client = MongoClient(
        uri,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=5000,
        tlsCAFile=tls_ca_file,  # Use certificate if available
    )
    return _docdb_client


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(plain_password, password_hash)
    except Exception:
        return False


def _require_jwt_config() -> None:
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="JWT not configured (JWT_SECRET missing)")


def _create_access_token(subject: str) -> str:
    _require_jwt_config()
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "sub": subject,
        "iat": int(now.timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def require_auth(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Dict[str, Any]:
    _require_jwt_config()
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        return jwt.decode(
            creds.credentials,
            JWT_SECRET,
            algorithms=["HS256"],
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
            options={"verify_exp": False},
        )
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, str]


@app.post("/auth/login", response_model=LoginResponse)
async def auth_login(body: LoginRequest):
    username = str(body.username).strip()
    if not username or not body.password:
        raise HTTPException(status_code=400, detail="username and password are required")
    if AUTH_DEV_MODE:
        if not AUTH_DEV_USERNAME or not AUTH_DEV_PASSWORD:
            raise HTTPException(
                status_code=500,
                detail="Auth dev mode enabled but AUTH_DEV_USERNAME/AUTH_DEV_PASSWORD not set",
            )
        if username != AUTH_DEV_USERNAME or body.password != AUTH_DEV_PASSWORD:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        dev_user = {"username": AUTH_DEV_USERNAME, "email": AUTH_DEV_EMAIL or ""}
        token = _create_access_token(subject=AUTH_DEV_USERNAME)
        return LoginResponse(access_token=token, user=dev_user)

    def _docdb_check(username_value: str, plain_password: str) -> Dict[str, str]:
        client = get_docdb_client()
        client.admin.command("ping")
        _uri, db_name, users_collection_name = get_docdb_settings()
        db = client[db_name]
        users = db[users_collection_name]
        doc = users.find_one({"username": username_value})
        if not doc:
            doc = users.find_one({"email": username_value})
        if not doc:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        password_hash = doc.get("password_hash") or doc.get("passwordHash")
        if not isinstance(password_hash, str) or not password_hash:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        if not verify_password(plain_password, password_hash):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        return {
            "username": str(doc.get("username") or username_value),
            "email": str(doc.get("email") or ""),
        }

    try:
        user_info = await asyncio.wait_for(
            asyncio.to_thread(_docdb_check, username, body.password),
            timeout=DOCDB_AUTH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail="Auth service timed out")
    except HTTPException:
        raise
    except PyMongoError as e:
        logger.error(f"DocumentDB auth error: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Auth service unavailable")
    except Exception as e:
        logger.error(f"Unexpected auth error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Auth service error: {type(e).__name__}: {e}")
    token = _create_access_token(subject=username)
    return LoginResponse(access_token=token, user=user_info)


# CHANGE 1: Updated index name to consolidated index
INDEX_NAME = "video_clips_3_lucene"
VECTOR_PIPELINE = "vector-norm-pipeline-consolidated-index-rrf"
VECTOR_PIPELINE_3_VECTOR = "vector-norm-pipeline-video-clips-3-vector-rrf"
MIN_SCORE = 0.5
INNER_MIN_SCORE_VISUAL = INNER_MIN_SCORE_AUDIO = INNER_MIN_SCORE_TRANSCRIPTION = INNER_MIN_SCORE = 0.6
INNER_TOP_K = 100
TOP_K = 50

# Intent-based search pipelines for Marengo 3
VECTOR_PIPELINE_3_VISUAL = "vector-norm-pipeline-video-clips-3-visual-intent"
VECTOR_PIPELINE_3_AUDIO = "vector-norm-pipeline-video-clips-3-audio-intent"
VECTOR_PIPELINE_3_TRANSCRIPT = "vector-norm-pipeline-video-clips-3-text-intent"
VECTOR_PIPELINE_3_BALANCED = "vector-norm-pipeline-video-clips-3-balanced-intent"

# Combination search pipelines for Marengo 3 (7 search options)
VECTOR_PIPELINE_3_VISUAL_AUDIO = "vector-norm-pipeline-video-clips-3-visual-audio-rrf"
VECTOR_PIPELINE_3_VISUAL_TRANSCRIPTION = "vector-norm-pipeline-video-clips-3-visual-transcription-rrf"
VECTOR_PIPELINE_3_AUDIO_TRANSCRIPTION = "vector-norm-pipeline-video-clips-3-audio-transcription-rrf"

# Visual_Audio combination pipelines with focus variants
VECTOR_PIPELINE_3_VISUAL_AUDIO_VISUAL_FOCUS = "vector-norm-pipeline-video-clips-3-visual-audio-visual-focus-rrf"
VECTOR_PIPELINE_3_VISUAL_AUDIO_AUDIO_FOCUS = "vector-norm-pipeline-video-clips-3-visual-audio-audio-focus-rrf"
VECTOR_PIPELINE_3_VISUAL_AUDIO_BALANCED = "vector-norm-pipeline-video-clips-3-visual-audio-balanced-rrf"

# Visual_Transcription combination pipelines with focus variants
VECTOR_PIPELINE_3_VISUAL_TRANSCRIPTION_VISUAL_FOCUS = "vector-norm-pipeline-video-clips-3-visual-transcription-visual-focus-rrf"
VECTOR_PIPELINE_3_VISUAL_TRANSCRIPTION_TEXT_FOCUS = "vector-norm-pipeline-video-clips-3-visual-transcription-text-focus-rrf"
VECTOR_PIPELINE_3_VISUAL_TRANSCRIPTION_BALANCED = "vector-norm-pipeline-video-clips-3-visual-transcription-balanced-rrf"

# Audio_Transcription combination pipelines with focus variants
VECTOR_PIPELINE_3_AUDIO_TRANSCRIPTION_AUDIO_FOCUS = "vector-norm-pipeline-video-clips-3-audio-transcription-audio-focus-rrf"
VECTOR_PIPELINE_3_AUDIO_TRANSCRIPTION_TEXT_FOCUS = "vector-norm-pipeline-video-clips-3-audio-transcription-text-focus-rrf"
VECTOR_PIPELINE_3_AUDIO_TRANSCRIPTION_BALANCED = "vector-norm-pipeline-video-clips-3-audio-transcription-balanced-rrf"

# Intent-to-weights mapping for RRF pipeline (visual, audio, transcription)
INTENT_WEIGHTS = {
    "VISUAL":   [0.8, 0.1, 0.1],   # visual-focused
    "AUDIO":    [0.05, 0.8, 0.15],   # audio-focused
    "TRANSCRIPT": [0.05, 0.15, 0.8], # text-focused
    "BALANCED": [0.34, 0.33, 0.33] # balanced across all
}

# Combination weights for RRF pipeline (for 2-modality searches)
COMBINATION_WEIGHTS = {
    # Visual_Audio weights: [visual, audio]
    "VISUAL_AUDIO_VISUAL_FOCUS": [0.95, 0.05],
    "VISUAL_AUDIO_AUDIO_FOCUS": [0.2, 0.8],
    "VISUAL_AUDIO_BALANCED": [0.8, 0.2],
    
    # # Visual_Transcription weights: [visual, transcription]
    # "VISUAL_TRANSCRIPTION_VISUAL_FOCUS": [0.95, 0.05],
    # "VISUAL_TRANSCRIPTION_TEXT_FOCUS": [0.05, 0.95],
    # "VISUAL_TRANSCRIPTION_BALANCED": [0.5, 0.5],
    
    # # Audio_Transcription weights: [audio, transcription]
    # "AUDIO_TRANSCRIPTION_AUDIO_FOCUS": [0.95, 0.05],
    # "AUDIO_TRANSCRIPTION_TEXT_FOCUS": [0.05, 0.95],
    # "AUDIO_TRANSCRIPTION_BALANCED": [0.5, 0.5],
}

# Modality preference keywords for combination searches (including all verb tenses)
VISUAL_KEYWORDS = [
    # Base forms
    "look", "see", "watch", "appear", "show", "display", "view", "scene", 
    "color", "bright", "dark", "visible", "visual", "image", "picture",
    "frame", "shot", "angle", "perspective", "background", "foreground",
    # Continuous tenses
    "looking", "seeing", "watching", "appearing", "showing", "displaying", "viewing",
    # Past tenses
    "looked", "saw", "watched", "appeared", "showed", "displayed", "viewed",
    # Past participles
    "seen", "shown",

    "drinking"
]

AUDIO_KEYWORDS = [
    # Base forms
    "sound", "hear", "listen", "audio", "music", "song", "voice", "speak",
    "talk", "say", "noise", "loud", "quiet", "volume", "tone", "pitch",
    "melody", "rhythm", "beat", "acoustic", "sonic",
    # Continuous tenses
    "hearing", "listening", "speaking", "talking", "saying", "sounding",
    # Past tenses
    "heard", "listened", "spoke", "talked", "said", "sounded",
    # Past participles
    "spoken",

    "screaming"
]

TEXT_KEYWORDS = [
    # Base forms
    "say", "said", "mention", "word", "phrase", "quote", "text", "transcript",
    "speak", "talk", "dialogue", "conversation", "discuss", "explain",
    "describe", "tell", "narrate", "caption", "subtitle",
    # Continuous tenses
    "saying", "mentioning", "speaking", "talking", "discussing", "explaining",
    "describing", "telling", "narrating",
    # Past tenses
    "mentioned", "discussed", "explained", "described", "told", "narrated",
    # Past participles
    "spoken", "mentioned", "discussed", "explained", "described", "told", "narrated"
]


# Initialize clients at startup
opensearch_client: Optional[OpenSearch] = None
bedrock_runtime = None
s3_client = None
vector_pipeline_exists = False
hybrid_pipeline_exists = False


def ensure_search_ready() -> None:
    if opensearch_client is None or bedrock_runtime is None or s3_client is None:
        raise HTTPException(status_code=503, detail="Search service not initialized")


@app.on_event("startup")
async def startup_event():
    """Initialize clients and pipelines on application startup"""
    global opensearch_client, bedrock_runtime, s3_client, vector_pipeline_exists, hybrid_pipeline_exists

    strict_startup = os.environ.get("STRICT_STARTUP", "true").strip().lower() in {"1", "true", "yes", "y", "on"}
    if not os.environ.get("OPENSEARCH_CLUSTER_HOST"):
        logger.warning(
            "OPENSEARCH_CLUSTER_HOST is not set; skipping search initialization. "
            "Search/list/upload endpoints will return 503 until configured."
        )
        return
    try:
        logger.info("Initializing clients...")
        opensearch_client = get_opensearch_client()
        bedrock_runtime = boto3.client("bedrock-runtime", region_name="us-east-1")
        s3_client = boto3.client("s3", region_name="us-east-1")

        logger.info("Initializing search pipelines...")
        hybrid_pipeline_exists = _create_hybrid_search_pipeline(opensearch_client)
        vector_pipeline_exists = _create_vector_search_pipeline(opensearch_client)
        _create_vector_search_pipeline_3_vector(opensearch_client)

        logger.info("Creating combination search pipelines for Marengo 3...")
        _create_combination_pipelines(opensearch_client)

        logger.info("✓ All clients and pipelines initialized successfully")
    except Exception as e:
        logger.error(f"✗ Startup initialization failed: {e}", exc_info=True)
        opensearch_client = None
        bedrock_runtime = None
        s3_client = None
        vector_pipeline_exists = False
        hybrid_pipeline_exists = False
        if strict_startup:
            raise


class SearchRequest(BaseModel):
    query_text: Optional[str] = None
    image_base64: Optional[str] = None
    top_k: int = 10
    search_type: str = "hybrid"
    categories: Optional[List[str]] = None
    min_relevance: Optional[float] = None
    max_segments_per_video: Optional[int] = None


class VideoMetadata(BaseModel):
    video_id: str
    video_path: str
    title: Optional[str] = None
    thumbnail_url: Optional[str] = None
    duration: Optional[float] = None
    upload_date: Optional[str] = None
    clips_count: int = 0


class VideosListResponse(BaseModel):
    videos: List[VideoMetadata]
    total: int


class SearchResponse(BaseModel):
    query: str
    classified_intent: Optional[str] = None  
    weights_used: Optional[List[Any]] = []
    search_type: str
    total: int
    clips: List[Dict]


@app.get("/health")
async def health_check():
    """Health check endpoint for ECS task"""
    return {"status": "healthy", "service": "video-search"}


@app.post("/search", response_model=SearchResponse)
async def search_videos(request: SearchRequest, _auth: Dict[str, Any] = Depends(require_auth)):
    """
    Unified search endpoint - handles both text and image searches
    - Text search: Uses query_text with specified search_type
    - Image search: Uses image_base64, generates embedding, performs image-specific search
    """
    try:
        ensure_search_ready()
        query_text = request.query_text
        image_base64 = request.image_base64
        top_k = request.top_k
        search_type = request.search_type
        INDEX_NAME = "video_clips_consolidated"

        # Validate that at least one input is provided
        if not query_text and not image_base64:
            raise HTTPException(
                status_code=400, detail="Either query_text or image_base64 is required"
            )

        # IMAGE SEARCH PATH
        if image_base64:
            logger.info(f"📷 Image search requested (top_k: {top_k})")

            # Validate image
            is_valid, error_msg = validate_image(image_base64)
            if not is_valid:
                raise HTTPException(status_code=400, detail=error_msg)

            logger.info("✓ Image validation passed")
            logger.info(
                f"Processing image base64 of length: {len(image_base64)} characters"
            )

            # Generate image embedding
            logger.info("🔄 Generating image embedding from base64 using Marengo")
            query_embedding = generate_image_embedding(bedrock_runtime, image_base64)

            if not query_embedding:
                raise HTTPException(
                    status_code=500, detail="Failed to generate image embedding"
                )

            logger.info(
                f"✓ Generated image embedding with {len(query_embedding)} dimensions"
            )

            # Perform image-specific search
            logger.info("🔍 Performing image-specific search using emb_vis_image")
            results = search_with_image(
                opensearch_client, query_embedding, top_k, INDEX_NAME
            )

            query_display = ""  # Empty query for image search
            search_type_display = "image"

        # TRANSCRIPT SEARCH PATH
        else:
            logger.info(
                f"🔍 Text search: '{query_text}' (type: {search_type}, top_k: {top_k})"
            )
            logger.info("Generating embedding from text using Marengo")
            query_embedding = generate_text_embedding(bedrock_runtime, str(query_text))

            if not query_embedding:
                raise HTTPException(
                    status_code=500, detail="Failed to generate query embedding"
                )

            logger.info(
                f"Generated text embedding with {len(query_embedding)} dimensions"
            )

            # Perform search based on type for text queries
            if search_type == "hybrid":
                results = hybrid_search(
                    opensearch_client,
                    query_embedding,
                    str(query_text),
                    top_k,
                    INDEX_NAME,
                )
            elif search_type == "vector":
                results = vector_search(
                    opensearch_client, query_embedding, top_k, INDEX_NAME
                )
            elif search_type == "visual":
                results = visual_search(
                    opensearch_client, query_embedding, top_k, INDEX_NAME
                )
            elif search_type == "audio":
                results = audio_search(
                    opensearch_client, query_embedding, top_k, INDEX_NAME
                )
            # elif search_type == 'text':
            #     results = text_search(opensearch_client, query_text, top_k)
            else:
                raise HTTPException(
                    status_code=400, detail=f"Invalid search_type: {search_type}"
                )

            query_display = query_text
            search_type_display = search_type

        # Convert S3 paths to presigned URLs
        results = convert_s3_to_presigned_urls(s3_client, results)

        logger.info(f"✓ Search completed, found {len(results)} results")

        return SearchResponse(
            query=str(query_display),
            search_type=search_type_display,
            total=len(results),
            clips=results,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in search: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search-3", response_model=SearchResponse)
async def search_videos_marengo3(request: SearchRequest, _auth: Dict[str, Any] = Depends(require_auth)):
    """
    Marengo 3 unified search endpoint with intent classification
    - Text only: Classifies intent first, then generates embedding via Marengo 3
    - Image only: Uses image_base64, generates embedding via Marengo 3
    - Combined: Uses both query_text and image_base64 for multimodal search

    Intent classification (for text queries):
    - VISUAL: Focus on visual embeddings
    - AUDIO: Focus on audio embeddings
    - TRANSCRIPT: Focus on transcription embeddings
    - BALANCED: Use all three with balanced weights
    """
    try:
        ensure_search_ready()
        query_text = request.query_text
        image_base64 = request.image_base64
        top_k = request.top_k
        search_type = request.search_type
        categories = request.categories
        min_relevance = request.min_relevance
        max_segments_per_video = request.max_segments_per_video

        intent_pipeline_map = {
        "VISUAL": VECTOR_PIPELINE_3_VISUAL,
        "AUDIO": VECTOR_PIPELINE_3_AUDIO,
        "TRANSCRIPT": VECTOR_PIPELINE_3_TRANSCRIPT,
        "BALANCED": VECTOR_PIPELINE_3_BALANCED,
    }

        # Validate that at least one input is provided
        if not query_text and not image_base64:
            raise HTTPException(
                status_code=400, detail="Either query_text or image_base64 is required"
            )

        # Validate image if provided
        if image_base64:
            is_valid, error_msg = validate_image(image_base64)
            if not is_valid:
                raise HTTPException(status_code=400, detail=error_msg)
            logger.info("✓ Image validation passed")

        # Determine search type for logging
        if query_text and image_base64:
            logger.info(
                f"🔄 Multimodal search (Marengo 3): text='{query_text[:50]}...' + image (top_k: {top_k})"
            )
            search_input_type = "multimodal"
        elif image_base64:
            logger.info(f"📷 Image-only search (Marengo 3) (top_k: {top_k})")
            search_input_type = "image"
        else:
            logger.info(
                f"🔍 Text-only search (Marengo 3): '{query_text}' (type: {search_type}, top_k: {top_k})"
            )
            search_input_type = "text"

        # STEP 1 & 2: Run intent classification and embedding generation CONCURRENTLY
        classified_intent = None
        query_embedding = None

        # COMMENTED OUT: Intent classification temporarily disabled
        if query_text and not image_base64 and search_type == "vector":
            # For text-only vector search: Run BOTH intent classification and embedding generation in parallel
            logger.info(
                "📊 Step 1 & 2: Running intent classification and embedding generation concurrently..."
            )

            # Create both tasks
            # intent_task = classify_query_intent(bedrock_runtime, query_text)
            intent_task = detect_visual_audio_focus_llm(bedrock_runtime, query_text)
            embedding_task = asyncio.to_thread(
                generate_embedding_marengo3,
                bedrock_runtime,
                text=query_text,
                image_base64=image_base64,
            )

            # Run both concurrently and wait for both to complete
            classified_intent, query_embedding = await asyncio.gather(
                intent_task, embedding_task
            )

            logger.info(f"✓ Intent classification result: {classified_intent}")
            logger.info(
                f"✓ Generated {search_input_type} embedding (Marengo 3) with {len(query_embedding) if query_embedding else 0} dimensions"
            )

            # # Map intent to search type
            # intent_based_search_type = get_search_type_from_intent(classified_intent)
            # logger.info(
            #     f"📊 Mapped intent '{classified_intent}' to search_type: '{intent_based_search_type}'"
            # )
        else:
            # For other cases (image, multimodal, or direct modality search): Only generate embedding
            logger.info(
                f"� Step 2:  Generating {search_input_type} embedding using Marengo 3"
            )
            query_embedding = generate_embedding_marengo3(
                bedrock_runtime, text=query_text, image_base64=image_base64
            )
            classified_intent = "VISUAL_FOCUS"
        logger.info(
            f"✓ Generated {search_input_type} embedding (Marengo 3) with {len(query_embedding) if query_embedding else 0} dimensions"
        )

        if not query_embedding:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate {search_input_type} embedding (Marengo 3)",
            )

        # STEP 3: Perform search based on type
        logger.info(f"📊 Step 3: Performing {search_type} search (Marengo 3)")

        if search_type == "hybrid":
            logger.info(
                "⚠️ Hybrid search not yet implemented for Marengo 3, using vector search instead"
            )
            results = vector_search_marengo3(
                opensearch_client, query_embedding, top_k, "video_clips_3_lucene", 
                preference = classified_intent if classified_intent else "BALANCED", 
                categories=categories, min_relevance=min_relevance, max_segments_per_video=max_segments_per_video
            )
        elif search_type == "vector":
            # Using balanced vector search (all 3 modalities)
            logger.info("📊 Using balanced vector search (all 3 modalities)")
            results = vector_search_marengo3(
                opensearch_client, query_embedding, top_k, "video_clips_3_lucene", 
                preference = classified_intent if classified_intent else "BALANCED", 
                categories=categories, min_relevance=min_relevance, max_segments_per_video=max_segments_per_video
            )
        elif search_type == "visual":
            results = visual_search_marengo3(
                opensearch_client, query_embedding, top_k, "video_clips_3_lucene", 
                categories=categories, min_relevance=min_relevance, max_segments_per_video=max_segments_per_video
            )
        elif search_type == "audio":
            results = audio_search_marengo3(
                opensearch_client, query_embedding, top_k, "video_clips_3_lucene", 
                categories=categories, min_relevance=min_relevance, max_segments_per_video=max_segments_per_video
            )
        # elif search_type == "transcription":
        #     results = transcription_search_marengo3(
        #         opensearch_client, query_embedding, top_k, "video_clips_3_lucene"
        #     )
        # elif search_type == "visual_audio":
        #     results = vector_search_visual_audio_marengo3(
        #         opensearch_client, query_embedding, top_k, "video_clips_3_lucene", query_text
        #     )
        # elif search_type == "visual_transcription":
        #     results = vector_search_visual_transcription_marengo3(
        #         opensearch_client, query_embedding, top_k, "video_clips_3_lucene", query_text
        #     )
        # elif search_type == "audio_transcription":
        #     results = vector_search_audio_transcription_marengo3(
        #         opensearch_client, query_embedding, top_k, "video_clips_3_lucene", query_text
        #     )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid search_type: {search_type}. Supported: vector, visual, audio, transcription, visual_audio, visual_transcription, audio_transcription",
            )

        query_display = query_text if query_text else ""
        search_type_display = search_type

        # Apply client-side filters (min_relevance and max_segments_per_video)
        # Both filters use normalized RRF scores from parse_search_results_vector
        results = apply_post_filters(results, min_relevance, max_segments_per_video)

        # Convert S3 paths to presigned URLs
        results = convert_s3_to_presigned_urls(s3_client, results)

        logger.info(f"✓ Search (Marengo 3) completed, found {len(results)} results")

        # Retrieve actual weights from OpenSearch pipeline configuration
        weights_used = []
        if classified_intent and classified_intent in intent_pipeline_map:
            try:
                pipeline_id = intent_pipeline_map[classified_intent]
                pipeline_response = opensearch_client.search_pipeline.get(id=pipeline_id)

                weights_used =  [str(pipeline_response)]
            except Exception as e:
                logger.warning(f"Failed to retrieve weights from pipeline: {e}")
        else:
            weights_used = []

        return SearchResponse(
            query=query_display,
            classified_intent=classified_intent,
            weights_used=weights_used,
            search_type=search_type_display,
            total=len(results),
            clips=results,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in search-3: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/list", response_model=VideosListResponse)
async def list_all_videos(_auth: Dict[str, Any] = Depends(require_auth)):
    """
    Get all unique videos from the OpenSearch index
    Returns video metadata including S3 paths and clip counts
    """
    try:
        ensure_search_ready()
        # Get all unique videos from OpenSearch
        videos = get_all_unique_videos(opensearch_client)

        # Transform to response format
        video_list = []
        for video in videos:
            # Generate presigned URL for private S3 bucket access
            presigned_url = convert_s3_to_presigned_url(s3_client, video["video_path"])

            video_list.append(
                VideoMetadata(
                    video_id=video["video_id"],
                    video_path=presigned_url if presigned_url else video["video_path"],
                    title=video.get("clip_text") or f"Video {video['video_id'][:8]}",
                    thumbnail_url=video.get("thumbnail_url"),
                    duration=video.get("duration"),
                    upload_date=video.get("upload_date"),
                    clips_count=video.get("clips_count", 0),
                )
            )

        return VideosListResponse(videos=video_list, total=len(video_list))

    except Exception as e:
        logger.error(f"Error in list_videos: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-upload-presigned-url")
async def generate_upload_url(
    filename: str,
    file_size: int = None,
    category: Optional[str] = None,
    _auth: Dict[str, Any] = Depends(require_auth),
):
    """
    Generate presigned URLs for S3 upload from frontend
    - For files < 100MB: Single PUT upload
    - For files >= 100MB: Multipart upload with multiple presigned URLs
    """
    try:
        ensure_search_ready()
        # Check if s3_client is initialized
        if s3_client is None:
            raise HTTPException(
                status_code=503,
                detail="S3 client not initialized. Service may still be starting up.",
            )

        if not filename or len(filename.strip()) == 0:
            raise HTTPException(status_code=400, detail="filename is required")

        # Sanitize filename
        sanitized_name = "".join(
            c if c.isalnum() or c in ".-_" else "_" for c in filename
        )

        # Sanitize category
        category_slug = (category or "Uncategorized").replace(",", "|").replace("/", "_").strip()
        if not category_slug:
            category_slug = "Uncategorized"
            
        s3_key = f"{category_slug}/{sanitized_name}"

        # Get bucket name from environment
        bucket_name = os.environ.get("AWS_S3_BUCKET")
        if not bucket_name:
            raise ValueError("AWS_S3_BUCKET environment variable not set")

        MULTIPART_THRESHOLD = 100 * 1024 * 1024  # 100MB
        CHUNK_SIZE = 10 * 1024 * 1024  # 10MB chunks for multipart
        PRESIGNED_URL_EXPIRY = 3600  # 1 hour for presigned URLs

        # CASE 1: SINGLE PUT (files < 100MB)
        if file_size is None or file_size < MULTIPART_THRESHOLD:
            logger.info(f"Single PUT upload for: {s3_key} (size: {file_size or 'unknown'})")
            
            presigned_url = s3_client.generate_presigned_url(
                "put_object",
                Params={"Bucket": bucket_name, "Key": s3_key, "ContentType": "video/mp4"},
                ExpiresIn=PRESIGNED_URL_EXPIRY,
            )

            logger.info(f"✓ Generated single presigned URL for: {s3_key}")
            return {
                "presigned_url": presigned_url,
                "s3_key": s3_key,
                "s3_path": f"s3://{bucket_name}/{s3_key}",
                "expires_in": PRESIGNED_URL_EXPIRY,
                "type": "single"
            }

        # CASE 2: MULTIPART UPLOAD (files >= 100MB)
        else:
            logger.info(f"Multipart upload for: {s3_key} (size: {file_size / (1024**2):.2f}MB)")
            
            # Initiate multipart upload
            multipart_response = s3_client.create_multipart_upload(
                Bucket=bucket_name,
                Key=s3_key,
                ContentType="video/mp4"
            )
            upload_id = multipart_response["UploadId"]
            logger.info(f"✓ Initiated multipart upload with ID: {upload_id}")

            # Calculate number of parts needed
            num_parts = math.ceil(file_size / CHUNK_SIZE)
            logger.info(f"Generating {num_parts} presigned URLs for {num_parts} parts")

            # Generate presigned URLs for each part
            presigned_urls = []
            for part_num in range(1, num_parts + 1):
                presigned_url = s3_client.generate_presigned_url(
                    "upload_part",
                    Params={
                        "Bucket": bucket_name,
                        "Key": s3_key,
                        "UploadId": upload_id,
                        "PartNumber": part_num
                    },
                    ExpiresIn=PRESIGNED_URL_EXPIRY,
                )
                presigned_urls.append(presigned_url)

            logger.info(f"✓ Generated {len(presigned_urls)} presigned URLs for multipart upload")

            return {
                "presigned_urls": presigned_urls,
                "uploadId": upload_id,
                "s3_key": s3_key,
                "s3_path": f"s3://{bucket_name}/{s3_key}",
                "expires_in": PRESIGNED_URL_EXPIRY,
                "type": "multipart",
                "chunk_size": CHUNK_SIZE
            }

    except ValueError as e:
        logger.error(f"Configuration error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating presigned URL: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class CompleteMultipartRequest(BaseModel):
    """Request body for completing multipart upload"""
    uploadId: str
    s3_key: str
    # Accept PartNumber as int (or string coercible to int) and validate shape.
    class Part(BaseModel):
        ETag: str
        PartNumber: int

    parts: List[Part]


@app.post("/complete-multipart-upload")
async def complete_multipart_upload(
    request: CompleteMultipartRequest, _auth: Dict[str, Any] = Depends(require_auth)
):
    """
    Complete a multipart S3 upload after all parts have been uploaded
    """
    try:
        ensure_search_ready()
        if s3_client is None:
            raise HTTPException(
                status_code=503,
                detail="S3 client not initialized. Service may still be starting up.",
            )

        upload_id = request.uploadId
        s3_key = request.s3_key
        parts = request.parts

        if not upload_id or not s3_key or not parts:
            raise HTTPException(
                status_code=400,
                detail="uploadId, s3_key, and parts are required"
            )

        bucket_name = os.environ.get("AWS_S3_BUCKET")
        if not bucket_name:
            raise ValueError("AWS_S3_BUCKET environment variable not set")

        logger.info(f"Completing multipart upload for: {s3_key} (uploadId: {upload_id})")
        logger.info(f"Received {len(parts)} parts to complete")

        # Complete the multipart upload
        try:
            # Boto3 requires PartNumber to be int and parts sorted ascending.
            parts_payload = sorted(
                ({"ETag": p.ETag, "PartNumber": p.PartNumber} for p in parts),
                key=lambda p: p["PartNumber"],
            )
            response = s3_client.complete_multipart_upload(
                Bucket=bucket_name,
                Key=s3_key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts_payload}
            )

            logger.info(f"✓ Multipart upload completed for: {s3_key}")
            logger.info(f"  ETag: {response.get('ETag')}")
            logger.info(f"  Location: {response.get('Location')}")

            return {
                "success": True,
                "s3_path": f"s3://{bucket_name}/{s3_key}",
                "message": f"Multipart upload completed for {s3_key}"
            }

        except s3_client.exceptions.NoSuchUpload:
            logger.error(f"Upload ID not found: {upload_id}")
            raise HTTPException(
                status_code=404,
                detail=f"Upload ID {upload_id} not found or has expired"
            )
        except Exception as e:
            logger.error(f"Error completing multipart upload: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to complete multipart upload: {str(e)}"
            )

    except ValueError as e:
        logger.error(f"Configuration error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in complete-multipart-upload: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def get_opensearch_client():
    """Initialize OpenSearch Cluster client"""
    opensearch_host = os.environ.get("OPENSEARCH_CLUSTER_HOST")
    if not opensearch_host:
        raise ValueError("OPENSEARCH_CLUSTER_HOST environment variable not set")

    opensearch_host = (
        opensearch_host.replace("https://", "").replace("http://", "").strip()
    )

    session = boto3.Session()
    credentials = session.get_credentials()

    auth = AWSV4SignerAuth(credentials, "us-east-1", "es")

    return OpenSearch(
        hosts=[{"host": opensearch_host, "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        pool_maxsize=20,
    )


def validate_image(image_base64: str) -> tuple[bool, str]:
    """
    Validate if the provided base64 string is a valid image
    Returns (is_valid, error_message)
    """
    try:
        # Check if base64 string is not empty
        if not image_base64 or len(image_base64.strip()) == 0:
            return False, "Image base64 string is empty"

        # Try to decode base64
        try:
            image_data = base64.b64decode(image_base64)
        except Exception as e:
            return False, f"Invalid base64 encoding: {str(e)}"

        # Check minimum size (at least 100 bytes)
        if len(image_data) < 100:
            return False, "Image data is too small"

        # Check maximum size (5MB)
        max_size = 5 * 1024 * 1024
        if len(image_data) > max_size:
            return False, "Image data exceeds 5MB limit"

        # Validate image magic bytes (signatures)
        valid_signatures = {
            b"\xff\xd8\xff": "jpeg",
            b"\x89\x50\x4e\x47": "png",
            b"\x47\x49\x46": "gif",
            b"\x52\x49\x46\x46": "webp",
        }

        is_valid_image = False
        for signature in valid_signatures:
            if image_data.startswith(signature):
                is_valid_image = True
                break

        if not is_valid_image:
            return (
                False,
                "Image format not supported. Supported formats: JPEG, PNG, GIF, WebP",
            )

        logger.info(f"✓ Image validation passed. Size: {len(image_data)} bytes")
        return True, ""

    except Exception as e:
        logger.error(f"Error validating image: {e}", exc_info=True)
        return False, f"Image validation error: {str(e)}"


def generate_text_embedding(bedrock_runtime, text: str) -> List[float]:
    """Generate embedding for text query using Bedrock Marengo"""
    try:
        request_body = {"inputType": "text", "inputText": text, "textTruncate": "none"}

        response = bedrock_runtime.invoke_model(
            modelId="us.twelvelabs.marengo-embed-2-7-v1:0",
            body=json.dumps(request_body),
            contentType="application/json",
            accept="application/json",
        )

        result = json.loads(response["body"].read())

        if "data" in result and len(result["data"]) > 0:
            return result["data"][0].get("embedding", [])

        return []

    except Exception as e:
        logger.error(f"Error generating text embedding: {e}", exc_info=True)
        return []


def generate_image_embedding(bedrock_runtime, image_base64: str) -> List[float]:
    """Generate embedding for image query using Bedrock Marengo with base64 image"""
    try:
        # Validate base64 string is not empty
        if not image_base64 or len(image_base64.strip()) == 0:
            logger.error("Image base64 string is empty")
            return []

        logger.info(
            f"Processing image base64 of length: {len(image_base64)} characters"
        )

        request_body = {
            "inputType": "image",
            "mediaSource": {"base64String": image_base64},
        }

        logger.info("Sending image embedding request to Marengo with base64 image")
        response = bedrock_runtime.invoke_model(
            modelId="us.twelvelabs.marengo-embed-2-7-v1:0",
            body=json.dumps(request_body),
            contentType="application/json",
            accept="application/json",
        )

        result = json.loads(response["body"].read())
        logger.info(f"Marengo response: {result}")

        if "data" in result and len(result["data"]) > 0:
            embedding = result["data"][0].get("embedding", [])
            logger.info(f"✓ Generated image embedding with {len(embedding)} dimensions")
            return embedding

        logger.warning(f"No embedding data in response. Response: {result}")
        return []

    except Exception as e:
        logger.error(f"Error generating image embedding: {e}", exc_info=True)
        return []


# ============ INTENT CLASSIFICATION FUNCTION ============


async def classify_query_intent(bedrock_runtime, query_text: str) -> str:
    """
    Classify user query intent using Bedrock Nova Micro model.
    Returns one of: VISUAL, AUDIO, TRANSCRIPT, or BALANCED
    """
    try:
        if not query_text or len(query_text.strip()) == 0:
            logger.info("Empty query, defaulting to BALANCED intent")
            return "BALANCED"

        prompt = f"""You are a modality classifier for a video library. Return EXACTLY ONE WORD from this list:
VISUAL, AUDIO, TRANSCRIPT, BALANCED.

Classify the following query into ONE of these categories:

1. VISUAL: The user is describing how something looks (objects, colors, scenes, actions).
2. AUDIO: The user is describing a sound (noises, music style, volume).
3. TRANSCRIPT: The user is searching for specific spoken words, quotes, names, or a transcript.
4. BALANCED: The query is abstract, emotional, or a mix.

Never explain. Never use punctuation. Output only one word.
INPUT: {query_text}"""

        logger.info(f"🔍 Classifying query intent: '{query_text[:50]}...'")

        request_body = {"messages": [{"role": "user", "content": [{"text": prompt}]}]}

        response = bedrock_runtime.invoke_model(
            modelId="amazon.nova-micro-v1:0",
            body=json.dumps(request_body),
            contentType="application/json",
            accept="application/json",
        )

        result = json.loads(response["body"].read())
        logger.info(f"Nova Micro response: {result}")
        intent = (
            result.get("output", [{}])
            .get("message", [{}])
            .get("content", [{}])[0]
            .get("text", "BALANCED")
            .strip()
            .upper()
        )

        # Validate intent is one of the allowed values
        valid_intents = ["VISUAL", "AUDIO", "TRANSCRIPT", "BALANCED"]
        if intent not in valid_intents:
            logger.warning(
                f"Invalid intent '{intent}' returned, defaulting to BALANCED"
            )
            intent = "BALANCED"

        logger.info(f"✓ Query intent classified as: {intent}")
        return intent

    except Exception as e:
        logger.error(f"Error classifying query intent: {e}", exc_info=True)
        logger.info("Defaulting to BALANCED intent due to classification error")
        return "BALANCED"


def get_search_type_from_intent(intent: str) -> str:
    """
    Map intent classification to search type for weighted search
    """
    intent_to_search_type = {
        "VISUAL": "visual",
        "AUDIO": "audio",
        "TRANSCRIPT": "transcription",
        "BALANCED": "vector",     # Use all three with balanced weights
    }
    return intent_to_search_type.get(intent, "vector")


async def detect_visual_audio_focus_llm(bedrock_runtime, query_text: str) -> str:
    """
    Detect visual vs audio focus for visual_audio searches using LLM (Nova Micro).
    Returns one of: VISUAL_FOCUS, AUDIO_FOCUS, or BALANCED
    """
    try:
        if not query_text or len(query_text.strip()) == 0:
            logger.info("Empty query, defaulting to BALANCED for visual_audio")
            return "BALANCED"

        prompt = f"""You are a modality classifier for video search. Return EXACTLY ONE WORD from this list:
VISUAL_FOCUS, AUDIO_FOCUS, BALANCED.

Classify the following query into ONE of these categories for a visual+audio search:

1. VISUAL_FOCUS: The user is primarily describing visual elements (objects, colors, scenes, actions, what things look like).
2. AUDIO_FOCUS: The user is primarily describing audio elements (sounds, music, voices, noises, what things sound like).
3. BALANCED: The query mentions both visual and audio equally, or is abstract/general.

Never explain. Never use punctuation. Output only one word.
INPUT: {query_text}"""

        logger.info(f"🔍 Detecting visual/audio focus: '{query_text[:50]}...'")

        request_body = {"messages": [{"role": "user", "content": [{"text": prompt}]}]}

        response = bedrock_runtime.invoke_model(
            modelId="amazon.nova-micro-v1:0",
            body=json.dumps(request_body),
            contentType="application/json",
            accept="application/json",
        )

        result = json.loads(response["body"].read())
        logger.info(f"Nova Micro response: {result}")
        focus = (
            result.get("output", [{}])
            .get("message", [{}])
            .get("content", [{}])[0]
            .get("text", "BALANCED")
            .strip()
            .upper()
        )

        # Validate focus is one of the allowed values
        valid_focuses = ["VISUAL_FOCUS", "AUDIO_FOCUS", "BALANCED"]
        if focus not in valid_focuses:
            logger.warning(
                f"Invalid focus '{focus}' returned, defaulting to BALANCED"
            )
            focus = "BALANCED"

        logger.info(f"✓ Visual/Audio focus detected as: {focus}")
        return focus

    except Exception as e:
        logger.error(f"Error detecting visual/audio focus: {e}", exc_info=True)
        logger.info("Defaulting to BALANCED due to detection error")
        return "BALANCED"


def detect_modality_preference(query_text: str, combination_type: str) -> str:
    """
    Analyze query text to detect modality preference for combination searches.
    
    Args:
        query_text: User's search query
        combination_type: One of 'visual_audio', 'visual_transcription', 'audio_transcription'
    
    Returns:
        Preference string like 'VISUAL_FOCUS', 'AUDIO_FOCUS', 'TEXT_FOCUS', or 'BALANCED'
    """
    if not query_text:
        return "BALANCED"
    
    query_lower = query_text.lower()
    
    # Count keyword occurrences
    visual_count = sum(1 for keyword in VISUAL_KEYWORDS if keyword in query_lower)
    audio_count = sum(1 for keyword in AUDIO_KEYWORDS if keyword in query_lower)
    text_count = sum(1 for keyword in TEXT_KEYWORDS if keyword in query_lower)
    
    logger.info(f"🔍 Modality keyword counts - Visual: {visual_count}, Audio: {audio_count}, Text: {text_count}")
    
    # Determine preference based on combination type
    if combination_type == "visual_audio":
        if visual_count > audio_count and visual_count > 0:
            preference = "VISUAL_FOCUS"
        elif audio_count > visual_count and audio_count > 0:
            preference = "AUDIO_FOCUS"
        else:
            preference = "BALANCED"
    
    elif combination_type == "visual_transcription":
        if visual_count > text_count and visual_count > 0:
            preference = "VISUAL_FOCUS"
        elif text_count > visual_count and text_count > 0:
            preference = "TEXT_FOCUS"
        else:
            preference = "BALANCED"
    
    elif combination_type == "audio_transcription":
        if audio_count > text_count and audio_count > 0:
            preference = "AUDIO_FOCUS"
        elif text_count > audio_count and text_count > 0:
            preference = "TEXT_FOCUS"
        else:
            preference = "BALANCED"
    
    else:
        preference = "BALANCED"
    
    logger.info(f"✓ Detected modality preference for {combination_type}: {preference}")
    return preference


async def detect_modality_preference_llm(bedrock_runtime, query_text: str, combination_type: str) -> str:
    """
    Analyze query text to detect modality preference for combination searches using LLM.
    For visual_audio: Uses LLM-based detection
    For other combinations: Falls back to keyword-based detection
    
    Args:
        bedrock_runtime: Bedrock runtime client
        query_text: User's search query
        combination_type: One of 'visual_audio', 'visual_transcription', 'audio_transcription'
    
    Returns:
        Preference string like 'VISUAL_FOCUS', 'AUDIO_FOCUS', 'TEXT_FOCUS', or 'BALANCED'
    """
    if not query_text:
        return "BALANCED"
    
    # For visual_audio, use LLM-based detection
    if combination_type == "visual_audio":
        return await detect_visual_audio_focus_llm(bedrock_runtime, query_text)
    
    # For other combination types, use keyword-based detection
    query_lower = query_text.lower()
    
    # Count keyword occurrences
    visual_count = sum(1 for keyword in VISUAL_KEYWORDS if keyword in query_lower)
    audio_count = sum(1 for keyword in AUDIO_KEYWORDS if keyword in query_lower)
    text_count = sum(1 for keyword in TEXT_KEYWORDS if keyword in query_lower)
    
    logger.info(f"🔍 Modality keyword counts - Visual: {visual_count}, Audio: {audio_count}, Text: {text_count}")
    
    # Determine preference based on combination type
    if combination_type == "visual_transcription":
        if visual_count > text_count and visual_count > 0:
            preference = "VISUAL_FOCUS"
        elif text_count > visual_count and text_count > 0:
            preference = "TEXT_FOCUS"
        else:
            preference = "BALANCED"
    
    elif combination_type == "audio_transcription":
        if audio_count > text_count and audio_count > 0:
            preference = "AUDIO_FOCUS"
        elif text_count > audio_count and text_count > 0:
            preference = "TEXT_FOCUS"
        else:
            preference = "BALANCED"
    
    else:
        preference = "BALANCED"
    
    logger.info(f"✓ Detected modality preference for {combination_type}: {preference}")
    return preference



def generate_embedding_marengo3(
    bedrock_runtime, text: Optional[str] = None, image_base64: Optional[str] = None
) -> List[float]:
    """
    Generate unified embedding for Marengo 3 - supports text, image, or both
    When both are provided, Marengo 3 generates a combined multimodal embedding
    """
    try:
        # Validate at least one input is provided
        if not text and not image_base64:
            logger.error("Either text or image_base64 must be provided")
            return []

        request_body = {}

        # Text-only request
        if text and not image_base64:
            logger.info(f"🔄 Generating text embedding (Marengo 3): '{text[:50]}...'")
            request_body = {"inputType": "text", "text": {"inputText": text}}

        # Image-only request
        elif image_base64 and not text:
            if not image_base64 or len(image_base64.strip()) == 0:
                logger.error("Image base64 string is empty")
                return []

            logger.info(
                f"🔄 Generating image embedding (Marengo 3) (base64 length: {len(image_base64)} chars)"
            )
            request_body = {
                "inputType": "image",
                "image": {"mediaSource": {"base64String": image_base64}},
            }

        # Multimodal request with both text and image
        else:
            if not image_base64 or len(image_base64.strip()) == 0:
                logger.error("Image base64 string is empty")
                return []

            logger.info(f"🔄 Generating multimodal embedding (Marengo 3): text + image")
            request_body = {
                "inputType": "text_image",
                "text_image": {
                    "inputText": text,
                    "mediaSource": {"base64String": image_base64},
                },
            }

        logger.info(f"📤 Invoking Marengo 3 model")
        response = bedrock_runtime.invoke_model(
            modelId="us.twelvelabs.marengo-embed-3-0-v1:0",
            body=json.dumps(request_body),
            contentType="application/json",
            accept="application/json",
        )

        result = json.loads(response["body"].read())
        logger.info(f"✓ Marengo 3 response received")

        if "data" in result and len(result["data"]) > 0:
            embedding = result["data"][0].get("embedding", [])
            input_type = (
                "multimodal (text+image)"
                if (text and image_base64)
                else ("image" if image_base64 else "text")
            )
            logger.info(
                f"✓ Generated {input_type} embedding (Marengo 3) with {len(embedding)} dimensions"
            )
            return embedding

        logger.warning(f"No embedding data in Marengo 3 response. Response: {result}")
        return []

    except Exception as e:
        logger.error(f"Error generating embedding (Marengo 3): {e}", exc_info=True)
        return []


def search_with_image(
    client, query_embedding: List[float], top_k: int = 10, index_name=None
) -> List[Dict]:
    """Image-specific search using emb_vis_image field"""
    if index_name is None:
        index_name = INDEX_NAME

    search_body = {
        "size": top_k,
        "query": {
            "knn": {
                "emb_vis_image": {
                    "vector": query_embedding,
                    "min_score": INNER_MIN_SCORE_VISUAL,
                }
            }
        },
        "_source": [
            "video_id",
            "video_path",
            "clip_id",
            "timestamp_start",
            "timestamp_end",
            "clip_text",
            "thumbnail_path",
            "video_name",
            "clip_duration",
            "video_duration_sec",
        ],
    }

    try:
        response = client.search(index=index_name, body=search_body)
        logger.info(
            f"✓ Image search completed, found {len(response.get('hits', {}).get('hits', []))} results"
        )
        return parse_search_results(response)

    except Exception as e:
        logger.error(f"Image search error: {e}", exc_info=True)
        return []


def convert_s3_to_presigned_urls(
    s3_client, results: List[Dict], expiration: int = 3600
) -> List[Dict]:
    """Convert S3 paths to presigned URLs in video_path and thumbnail_path fields"""
    for result in results:
        # Convert video_path to presigned URL
        video_path = result.get("video_path", "")
        if video_path.startswith("s3://"):
            try:
                s3_parts = video_path.replace("s3://", "").split("/", 1)
                bucket = s3_parts[0]
                key = s3_parts[1] if len(s3_parts) > 1 else ""

                presigned_url = s3_client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=expiration,
                )

                result["video_path"] = presigned_url

            except Exception as e:
                logger.warning(f"Error generating presigned URL for {video_path}: {e}")
                pass

        # Convert thumbnail_path to presigned URL
        thumbnail_path = result.get("thumbnail_path", "")
        if thumbnail_path and thumbnail_path.startswith("s3://"):
            try:
                s3_parts = thumbnail_path.replace("s3://", "").split("/", 1)
                bucket = s3_parts[0]
                key = s3_parts[1] if len(s3_parts) > 1 else ""

                presigned_url = s3_client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=expiration,
                )

                result["thumbnail_path"] = presigned_url
                # logger.info(f"✓ Generated presigned URL for thumbnail: {key}")

            except Exception as e:
                logger.warning(
                    f"Error generating presigned URL for thumbnail {thumbnail_path}: {e}"
                )
                pass

    return results


def convert_s3_to_presigned_url(
    s3_client, video_path: str, expiration: int = 3600
) -> Optional[str]:
    """Convert single S3 path to presigned URL"""
    if not video_path.startswith("s3://"):
        return None

    try:
        s3_parts = video_path.replace("s3://", "").split("/", 1)
        bucket = s3_parts[0]
        key = s3_parts[1] if len(s3_parts) > 1 else ""

        presigned_url = s3_client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expiration
        )

        return presigned_url

    except Exception as e:
        logger.warning(f"Error generating presigned URL for {video_path}: {e}")
        return None


def get_all_unique_videos(client) -> List[Dict]:
    """Get all unique videos from OpenSearch index"""
    search_body = {
        "size": 0,
        "aggs": {
            "unique_videos": {
                "terms": {"field": "video_id", "size": 10000},
                "aggs": {
                    "video_metadata": {
                        "top_hits": {
                            "size": 1,
                            "_source": ["video_id", "video_path", "clip_text"],
                        }
                    },
                    "clip_count": {"cardinality": {"field": "clip_id"}},
                },
            }
        },
    }

    try:
        response = client.search(index=INDEX_NAME, body=search_body)

        videos = []
        for bucket in response["aggregations"]["unique_videos"]["buckets"]:
            video_data = bucket["video_metadata"]["hits"]["hits"][0]["_source"]
            video_data["clips_count"] = bucket["clip_count"]["value"]
            videos.append(video_data)

        return videos

    except Exception as e:
        logger.error(f"Error fetching unique videos: {e}", exc_info=True)
        return []


# CHANGE 3: Updated hybrid_search to query emb_vis_text and emb_audio
def hybrid_search(
    client,
    query_embedding: List[float],
    query_text: str,
    top_k: int = 10,
    INDEX_NAME: str = "video_clips_consolidated",
) -> List[Dict]:
    """Hybrid search combining vector similarity on visual-text & audio + text matching"""
    search_body = {
        "size": top_k,
        "query": {
            "hybrid": {
                "queries": [
                    # Visual-text embedding (k-NN) - weight 0.5
                    {"knn": {"emb_vis_text": {"vector": query_embedding, "k": top_k}}},
                    # Audio embedding (k-NN) - weight 0.3
                    {"knn": {"emb_audio": {"vector": query_embedding, "k": top_k}}},
                    # Text matching (BM25) - weight 0.2
                    {
                        "match": {
                            "video_name": {"query": query_text, "fuzziness": "AUTO"}
                        }
                    },
                ]
            }
        },
        "_source": [
            "video_id",
            "video_path",
            "clip_id",
            "timestamp_start",
            "timestamp_end",
            "clip_text",
            "thumbnail_path",
            "video_name",
            "clip_duration",
            "video_duration_sec",
        ],
    }

    if hybrid_pipeline_exists:
        search_params = {
            "index": INDEX_NAME,
            "body": search_body,
            "search_pipeline": "hybrid-norm-pipeline",
        }
    else:
        search_params = {"index": INDEX_NAME, "body": search_body}

    try:
        response = client.search(**search_params)
        return parse_search_results(response)

    except Exception as e:
        logger.error(f"Hybrid search error: {e}", exc_info=True)
        return vector_search(client, query_embedding, top_k)


# CHANGE 4: Updated vector_search to query emb_vis_text and emb_audio
def vector_search(
    client,
    query_embedding: List[float],
    top_k: int = 10,
    INDEX_NAME: str = "video_clips_consolidated",
) -> List[Dict]:
    """Vector-only k-NN search on visual-text and audio embeddings with normalization"""
    search_body = {
        "size": TOP_K,
        "query": {
            "hybrid": {
                "queries": [
                    {
                        "knn": {
                            "emb_vis_text": {
                                "vector": query_embedding,
                                "min_score": INNER_MIN_SCORE_VISUAL,
                            }
                        }
                    },
                    {
                        "knn": {
                            "emb_audio": {
                                "vector": query_embedding,
                                "min_score": INNER_MIN_SCORE_AUDIO,
                            }
                        }
                    },
                ]
            }
        },
        "_source": [
            "video_id",
            "video_path",
            "clip_id",
            "timestamp_start",
            "timestamp_end",
            "clip_text",
            "thumbnail_path",
            "video_name",
            "clip_duration",
            "video_duration_sec",
        ],
    }
    # bool query did not work with search pipeline and also it allows us to have results matching the req. no.s of sub-queries
    # (its more of an atomic approach) -- TO TRY IT AGAIN TOMORROW
    # search_body = {
    # "size": TOP_K,
    # "query": {
    #     "bool": {
    #         "should": [
    #             {
    #                 "knn": {
    #                     "emb_vis_text": {
    #                         "vector": query_embedding,
    #                         "k": 100
    #                     }
    #                 }
    #             },
    #             {
    #                 "knn": {
    #                     "emb_audio": {
    #                         "vector": query_embedding,
    #                         "k": 100
    #                     }
    #                 }
    #             }
    #         ],
    #         "minimum_should_match": 1
    #     }
    # },
    # "_source": [
    #     "video_id", "video_path", "clip_id", "timestamp_start",
    #     "timestamp_end", "clip_text", "thumbnail_path",
    #     "video_name", "clip_duration", "video_duration_sec"
    #     ]
    # }
    ################################################################

    if vector_pipeline_exists:
        search_params = {
            "index": INDEX_NAME,
            "body": search_body,
            "search_pipeline": VECTOR_PIPELINE,
        }
    else:
        search_params = {"index": INDEX_NAME, "body": search_body}

    response = client.search(**search_params)
    return parse_search_results_vector(response)


# def text_search(client, query_text: str, top_k: int = 10) -> List[Dict]:
#     """Text-only BM25 search"""
#     search_body = {
#         "size": top_k,
#         "query": {
#             "match": {
#                 "video_name": {
#                     "query": query_text,
#                     "fuzziness": "AUTO"
#                 }
#             }
#         },
#         "_source": ["video_id", "video_path", "clip_id", "timestamp_start",
#                    "timestamp_end", "clip_text",  "thumbnail_path", "video_name", "clip_duration", "video_duration_sec"]
#     }

#     response = client.search(index=INDEX_NAME, body=search_body)
#     return parse_search_results(response)


def visual_search(
    client,
    query_embedding: List[float],
    top_k: int = 10,
    INDEX_NAME: str = "video_clips_consolidated",
) -> List[Dict]:
    """Visual-only k-NN search on visual-text embeddings"""
    search_body = {
        "size": top_k,
        "query": {
            "knn": {
                "emb_vis_text": {
                    "vector": query_embedding,
                    "min_score": INNER_MIN_SCORE_VISUAL,
                }
            }
        },
        "_source": [
            "video_id",
            "video_path",
            "clip_id",
            "timestamp_start",
            "timestamp_end",
            "clip_text",
            "thumbnail_path",
            "video_name",
            "clip_duration",
            "video_duration_sec",
        ],
    }

    response = client.search(index=INDEX_NAME, body=search_body)
    return parse_search_results(response)


def audio_search(
    client,
    query_embedding: List[float],
    top_k: int = 10,
    INDEX_NAME: str = "video_clips_consolidated",
) -> List[Dict]:
    """Audio-only k-NN search on audio embeddings"""
    search_body = {
        "size": top_k,
        "query": {
            "knn": {
                "emb_audio": {
                    "vector": query_embedding,
                    "min_score": INNER_MIN_SCORE_AUDIO,
                }
            }
        },
        "_source": [
            "video_id",
            "video_path",
            "clip_id",
            "timestamp_start",
            "timestamp_end",
            "clip_text",
            "thumbnail_path",
            "video_name",
            "clip_duration",
            "video_duration_sec",
        ],
    }

    response = client.search(index=INDEX_NAME, body=search_body)
    return parse_search_results(response)


# ============ NEW SEARCH FUNCTIONS FOR MARENGO 3 (emb_visual, emb_audio, emb_transcription) ============


def vector_search_marengo3_with_intent(
    client,
    query_embedding: List[float],
    intent: str,
    top_k: int = 10,
    INDEX_NAME: str = "video_clips_3_lucene",
) -> List[Dict]:
    """
    Vector search with intent-based weights (Marengo 3)
    Uses intent-specific search pipeline with RRF weights to focus on appropriate modality
    """
    # Map intent to pipeline
    intent_pipeline_map = {
        "VISUAL": VECTOR_PIPELINE_3_VISUAL,
        "AUDIO": VECTOR_PIPELINE_3_AUDIO,
        "TRANSCRIPT": VECTOR_PIPELINE_3_TRANSCRIPT,
        "BALANCED": VECTOR_PIPELINE_3_BALANCED,
    }

    pipeline_id = intent_pipeline_map.get(intent, VECTOR_PIPELINE_3_BALANCED)
    weights = INTENT_WEIGHTS.get(intent, INTENT_WEIGHTS["BALANCED"])

    logger.info(
        f"📊 Using intent-based pipeline for '{intent}': weights={weights}, pipeline={pipeline_id}"
    )

    search_body = {
        "size": TOP_K,
        "query": {
            "hybrid": {
                "queries": [
                    # Visual embedding (k-NN)
                    {
                        "knn": {
                            "emb_visual": {"vector": query_embedding, "k": INNER_TOP_K}
                        }
                    },
                    # Audio embedding (k-NN)
                    {
                        "knn": {
                            "emb_audio": {"vector": query_embedding, "k": INNER_TOP_K}
                        }
                    },
                    # For demo
                    # # Transcription embedding (k-NN)
                    # {
                    #     "knn": {
                    #         "emb_transcription": {
                    #             "vector": query_embedding,
                    #             "k": INNER_TOP_K,
                    #         }
                    #     }
                    # },
                ]
            }
        },
        "_source": [
            "video_id",
            "video_path",
            "clip_id",
            "timestamp_start",
            "timestamp_end",
            "clip_text",
            "thumbnail_path",
            "video_name",
            "clip_duration",
            "video_duration_sec",
        ],
    }

    search_params = {
        "index": INDEX_NAME,
        "body": search_body,
        "search_pipeline": pipeline_id,  # Use intent-specific pipeline
    }

    try:
        response = client.search(**search_params)
        logger.info(
            f"✓ Vector search with intent '{intent}' (Marengo 3) completed, found {len(response.get('hits', {}).get('hits', []))} results"
        )
        return parse_search_results_vector(response)
    except Exception as e:
        logger.error(f"Vector search with intent (Marengo 3) error: {e}", exc_info=True)
        return []


def vector_search_marengo3(
    client,
    query_embedding: List[float],
    top_k: int = 10,
    INDEX_NAME: str = "video_clips_3_lucene",
    preference: str = "BALANCED",
    categories: Optional[List[str]] = None,
    min_relevance: Optional[float] = None,
    max_segments_per_video: Optional[int] = None,
) -> List[Dict]:
    
    # Map preference to pipeline and weights
    pipeline_map = {
        "VISUAL_FOCUS": VECTOR_PIPELINE_3_VISUAL_AUDIO_VISUAL_FOCUS,
        "AUDIO_FOCUS": VECTOR_PIPELINE_3_VISUAL_AUDIO_AUDIO_FOCUS,
        "BALANCED": VECTOR_PIPELINE_3_VISUAL_AUDIO_BALANCED
    }
    
    weights_map = {
        "VISUAL_FOCUS": COMBINATION_WEIGHTS["VISUAL_AUDIO_VISUAL_FOCUS"],
        "AUDIO_FOCUS": COMBINATION_WEIGHTS["VISUAL_AUDIO_AUDIO_FOCUS"],
        "BALANCED": COMBINATION_WEIGHTS["VISUAL_AUDIO_BALANCED"]
    }
    
    selected_pipeline = pipeline_map[preference]
    selected_weights = weights_map[preference]
    
    logger.info(f"📊 Using {preference} pipeline for visual_audio search with weights {selected_weights}")
    
    search_body = {
        "size": TOP_K,
        "query": {
            "hybrid": {
                "queries": [
                    # Visual embedding (k-NN)
                    {
                        "knn": {
                            "emb_visual": {
                                "vector": query_embedding,
                                "k": INNER_TOP_K
                            }
                        }
                    },
                    # Audio embedding (k-NN)
                    {
                        "knn": {
                            "emb_audio": {
                                "vector": query_embedding,
                                "k": INNER_TOP_K
                            }
                        }
                    }
                ]
            }
        },
        "_source": ["video_id", "video_path", "clip_id", "timestamp_start",
                   "timestamp_end", "clip_text", "thumbnail_path", "video_name", "clip_duration", "video_duration_sec", "categories"]
    }

    # Apply advanced filters (categories, min_relevance, max_segments_per_video)
    search_body = _apply_advanced_filters(search_body, categories, min_relevance, max_segments_per_video)


    if vector_pipeline_exists:
        search_params = {
                "index": INDEX_NAME,
                "body": search_body,
                "search_pipeline": selected_pipeline  # Using preference-based pipeline
            }
    else:
        search_params = {
                "index": INDEX_NAME,
                "body": search_body
            }

    try:
        response = client.search(**search_params)
        logger.info(f"✓ Vector search ({preference}, Marengo 3) completed, found {len(response.get('hits', {}).get('hits', []))} results")
        
        # Always use standard parsing (collapse is handled post-search)
        return parse_search_results_vector(response)
    except Exception as e:
        logger.error(f"Vector search (Marengo 3) error: {e}", exc_info=True)
        return []

    """Vector search combining visual, audio, and transcription embeddings (Marengo 3)"""
    
    # search_body = {
    #     "size": TOP_K,
    #     "query": {
    #         "hybrid": {
    #             "queries": [
    #                 {
    #                     "knn": {
    #                         "emb_visual": {"vector": query_embedding, "k": INNER_TOP_K}
    #                     }
    #                 },
    #                 {
    #                     "knn": {
    #                         "emb_audio": {"vector": query_embedding, "k": INNER_TOP_K}
    #                     }
    #                 },
    #                 # For demo
    #                 # {
    #                 #     "knn": {
    #                 #         "emb_transcription": {
    #                 #             "vector": query_embedding,
    #                 #             "k": INNER_TOP_K,
    #                 #         }
    #                 #     }
    #                 # },
    #             ]
    #         }
    #     },
    #     "_source": [
    #         "video_id",
    #         "video_path",
    #         "clip_id",
    #         "timestamp_start",
    #         "timestamp_end",
    #         "clip_text",
    #         "thumbnail_path",
    #         "video_name",
    #         "clip_duration",
    #         "video_duration_sec",
    #     ],
    # }

    # if vector_pipeline_exists:
    #     search_params = {
    #         "index": INDEX_NAME,
    #         "body": search_body,
    #         "search_pipeline": VECTOR_PIPELINE_3_VECTOR,
    #     }
    # else:
    #     search_params = {"index": INDEX_NAME, "body": search_body}

    # try:
    #     response = client.search(**search_params)
    #     logger.info(
    #         f"✓ Vector search (Marengo 3) completed, found {len(response.get('hits', {}).get('hits', []))} results"
    #     )
    #     return parse_search_results_vector(response)
    # except Exception as e:
    #     logger.error(f"Vector search (Marengo 3) error: {e}", exc_info=True)
    #     return []


def visual_search_marengo3(
    client,
    query_embedding: List[float],
    top_k: int = 10,
    INDEX_NAME: str = "video_clips_3_lucene",
    categories: Optional[List[str]] = None,
    min_relevance: Optional[float] = None,
    max_segments_per_video: Optional[int] = None,
) -> List[Dict]:
    """Visual-only k-NN search on visual embeddings (Marengo 3)"""
    search_body = {
        "size": TOP_K,
        "query": {"knn": {"emb_visual": {"vector": query_embedding, "k": INNER_TOP_K}}},
        "_source": [
            "video_id",
            "video_path",
            "clip_id",
            "timestamp_start",
            "timestamp_end",
            "clip_text",
            "thumbnail_path",
            "video_name",
            "clip_duration",
            "video_duration_sec",
            "categories",
        ],
    }

    # Apply advanced filters (categories, min_relevance, max_segments_per_video)
    search_body = _apply_advanced_filters(search_body, categories, min_relevance, max_segments_per_video)

    try:
        response = client.search(index=INDEX_NAME, body=search_body)
        logger.info(
            f"✓ Visual search (Marengo 3) completed, found {len(response.get('hits', {}).get('hits', []))} results"
        )
        
        # Always use standard parsing (collapse is handled post-search)
        return parse_search_results(response)
    except Exception as e:
        logger.error(f"Visual search (Marengo 3) error: {e}", exc_info=True)
        return []


def audio_search_marengo3(
    client,
    query_embedding: List[float],
    top_k: int = 10,
    INDEX_NAME: str = "video_clips_3_lucene",
    categories: Optional[List[str]] = None,
    min_relevance: Optional[float] = None,
    max_segments_per_video: Optional[int] = None,
) -> List[Dict]:
    """Audio-only k-NN search on audio embeddings (Marengo 3)"""
    search_body = {
        "size": TOP_K,
        "query": {"knn": {"emb_audio": {"vector": query_embedding, "k": INNER_TOP_K}}},
        "_source": [
            "video_id",
            "video_path",
            "clip_id",
            "timestamp_start",
            "timestamp_end",
            "clip_text",
            "thumbnail_path",
            "video_name",
            "clip_duration",
            "video_duration_sec",
            "categories",
        ],
    }

    # Apply advanced filters (categories, min_relevance, max_segments_per_video)
    search_body = _apply_advanced_filters(search_body, categories, min_relevance, max_segments_per_video)

    try:
        response = client.search(index=INDEX_NAME, body=search_body)
        logger.info(
            f"✓ Audio search (Marengo 3) completed, found {len(response.get('hits', {}).get('hits', []))} results"
        )
        
        # Always use standard parsing (collapse is handled post-search)
        return parse_search_results(response)
    except Exception as e:
        logger.error(f"Audio search (Marengo 3) error: {e}", exc_info=True)
        return []


# def transcription_search_marengo3(
#     client,
#     query_embedding: List[float],
#     top_k: int = 10,
#     INDEX_NAME: str = "video_clips_3_lucene",
# ) -> List[Dict]:
#     """Transcription-only k-NN search on transcription embeddings (Marengo 3)"""
#     search_body = {
#         "size": TOP_K,
#         "query": {
#             "knn": {"emb_transcription": {"vector": query_embedding, "k": INNER_TOP_K}}
#         },
#         "_source": [
#             "video_id",
#             "video_path",
#             "clip_id",
#             "timestamp_start",
#             "timestamp_end",
#             "clip_text",
#             "thumbnail_path",
#             "video_name",
#             "clip_duration",
#             "video_duration_sec",
#         ],
#     }

#     try:
#         response = client.search(index=INDEX_NAME, body=search_body)
#         logger.info(
#             f"✓ Transcription search (Marengo 3) completed, found {len(response.get('hits', {}).get('hits', []))} results"
#         )
#         return parse_search_results(response)
#     except Exception as e:
#         logger.error(f"Transcription search (Marengo 3) error: {e}", exc_info=True)
#         return []


# # UNCOMMENTED: Re-enabled 7 search options for Marengo 3 (was using intent classification)
# def vector_search_visual_audio_marengo3(client, query_embedding: List[float], top_k: int = 10, INDEX_NAME: str = 'video_clips_3_lucene', query_text: str = None) -> List[Dict]:
#     """Vector search combining visual and audio embeddings with modality preference detection (Marengo 3)"""
    
#     # Detect modality preference from query text
#     preference = detect_modality_preference(query_text or "", "visual_audio")
    
#     # Map preference to pipeline and weights
#     pipeline_map = {
#         "VISUAL_FOCUS": VECTOR_PIPELINE_3_VISUAL_AUDIO_VISUAL_FOCUS,
#         "AUDIO_FOCUS": VECTOR_PIPELINE_3_VISUAL_AUDIO_AUDIO_FOCUS,
#         "BALANCED": VECTOR_PIPELINE_3_VISUAL_AUDIO_BALANCED
#     }
    
#     weights_map = {
#         "VISUAL_FOCUS": COMBINATION_WEIGHTS["VISUAL_AUDIO_VISUAL_FOCUS"],
#         "AUDIO_FOCUS": COMBINATION_WEIGHTS["VISUAL_AUDIO_AUDIO_FOCUS"],
#         "BALANCED": COMBINATION_WEIGHTS["VISUAL_AUDIO_BALANCED"]
#     }
    
#     selected_pipeline = pipeline_map[preference]
#     selected_weights = weights_map[preference]
    
#     logger.info(f"📊 Using {preference} pipeline for visual_audio search with weights {selected_weights}")
    
#     search_body = {
#         "size": TOP_K,
#         "query": {
#             "hybrid": {
#                 "queries": [
#                     # Visual embedding (k-NN)
#                     {
#                         "knn": {
#                             "emb_visual": {
#                                 "vector": query_embedding,
#                                 "k": INNER_TOP_K
#                             }
#                         }
#                     },
#                     # Audio embedding (k-NN)
#                     {
#                         "knn": {
#                             "emb_audio": {
#                                 "vector": query_embedding,
#                                 "k": INNER_TOP_K
#                             }
#                         }
#                     }
#                 ]
#             }
#         },
#         "_source": ["video_id", "video_path", "clip_id", "timestamp_start",
#                    "timestamp_end", "clip_text", "thumbnail_path", "video_name", "clip_duration", "video_duration_sec"]
#     }


#     if vector_pipeline_exists:
#         search_params = {
#                 "index": INDEX_NAME,
#                 "body": search_body,
#                 "search_pipeline": selected_pipeline  # Using preference-based pipeline
#             }
#     else:
#         search_params = {
#                 "index": INDEX_NAME,
#                 "body": search_body
#             }

#     try:
#         response = client.search(**search_params)
#         logger.info(f"✓ Vector search (visual+audio {preference}, Marengo 3) completed, found {len(response.get('hits', {}).get('hits', []))} results")
#         return parse_search_results(response)
#     except Exception as e:
#         logger.error(f"Vector search (visual+audio, Marengo 3) error: {e}", exc_info=True)
#         return []


# # UNCOMMENTED: Re-enabled 7 search options for Marengo 3 (was using intent classification)
# def vector_search_visual_transcription_marengo3(client, query_embedding: List[float], top_k: int = 10, INDEX_NAME: str = 'video_clips_3_lucene', query_text: str = None) -> List[Dict]:
#     """Vector search combining visual and transcription embeddings with modality preference detection (Marengo 3)"""
    
#     # Detect modality preference from query text
#     preference = detect_modality_preference(query_text or "", "visual_transcription")
    
#     # Map preference to pipeline and weights
#     pipeline_map = {
#         "VISUAL_FOCUS": VECTOR_PIPELINE_3_VISUAL_TRANSCRIPTION_VISUAL_FOCUS,
#         "TEXT_FOCUS": VECTOR_PIPELINE_3_VISUAL_TRANSCRIPTION_TEXT_FOCUS,
#         "BALANCED": VECTOR_PIPELINE_3_VISUAL_TRANSCRIPTION_BALANCED
#     }
    
#     weights_map = {
#         "VISUAL_FOCUS": COMBINATION_WEIGHTS["VISUAL_TRANSCRIPTION_VISUAL_FOCUS"],
#         "TEXT_FOCUS": COMBINATION_WEIGHTS["VISUAL_TRANSCRIPTION_TEXT_FOCUS"],
#         "BALANCED": COMBINATION_WEIGHTS["VISUAL_TRANSCRIPTION_BALANCED"]
#     }
    
#     selected_pipeline = pipeline_map[preference]
#     selected_weights = weights_map[preference]
    
#     logger.info(f"📊 Using {preference} pipeline for visual_transcription search with weights {selected_weights}")
#     search_body = {
#         "size": TOP_K,
#         "query": {
#             "hybrid": {
#                 "queries": [
#                     # Visual embedding (k-NN) - weight 0.6
#                     {
#                         "knn": {
#                             "emb_visual": {
#                                 "vector": query_embedding,
#                                 "k": INNER_TOP_K
#                             }
#                         }
#                     },
#                     # Transcription embedding (k-NN) - weight 0.4
#                     {
#                         "knn": {
#                             "emb_transcription": {
#                                 "vector": query_embedding,
#                                 "k": INNER_TOP_K
#                             }
#                         }
#                     }
#                 ]
#             }
#         },
#         "_source": ["video_id", "video_path", "clip_id", "timestamp_start",
#                    "timestamp_end", "clip_text", "thumbnail_path", "video_name", "clip_duration", "video_duration_sec"]
#     }

#     if vector_pipeline_exists:
#         search_params = {
#                 "index": INDEX_NAME,
#                 "body": search_body,
#                 "search_pipeline": selected_pipeline  # Using preference-based pipeline
#             }
#     else:
#         search_params = {
#                 "index": INDEX_NAME,
#                 "body": search_body
#             }

#     try:
#         response = client.search(**search_params)
#         logger.info(f"✓ Vector search (visual+transcription {preference}, Marengo 3) completed, found {len(response.get('hits', {}).get('hits', []))} results")
#         return parse_search_results_vector(response)
#     except Exception as e:
#         logger.error(f"Vector search (visual+transcription, Marengo 3) error: {e}", exc_info=True)
#         return []


# # UNCOMMENTED: Re-enabled 7 search options for Marengo 3 (was using intent classification)
# def vector_search_audio_transcription_marengo3(client, query_embedding: List[float], top_k: int = 10, INDEX_NAME: str = 'video_clips_3_lucene', query_text: str = None) -> List[Dict]:
#     """Vector search combining audio and transcription embeddings with modality preference detection (Marengo 3)"""
    
#     # Detect modality preference from query text
#     preference = detect_modality_preference(query_text or "", "audio_transcription")
    
#     # Map preference to pipeline and weights
#     pipeline_map = {
#         "AUDIO_FOCUS": VECTOR_PIPELINE_3_AUDIO_TRANSCRIPTION_AUDIO_FOCUS,
#         "TEXT_FOCUS": VECTOR_PIPELINE_3_AUDIO_TRANSCRIPTION_TEXT_FOCUS,
#         "BALANCED": VECTOR_PIPELINE_3_AUDIO_TRANSCRIPTION_BALANCED
#     }
    
#     weights_map = {
#         "AUDIO_FOCUS": COMBINATION_WEIGHTS["AUDIO_TRANSCRIPTION_AUDIO_FOCUS"],
#         "TEXT_FOCUS": COMBINATION_WEIGHTS["AUDIO_TRANSCRIPTION_TEXT_FOCUS"],
#         "BALANCED": COMBINATION_WEIGHTS["AUDIO_TRANSCRIPTION_BALANCED"]
#     }
    
#     selected_pipeline = pipeline_map[preference]
#     selected_weights = weights_map[preference]
    
#     logger.info(f"📊 Using {preference} pipeline for audio_transcription search with weights {selected_weights}")
#     search_body = {
#         "size": TOP_K,
#         "query": {
#             "hybrid": {
#                 "queries": [
#                     # Audio embedding (k-NN) - weight 0.5
#                     {
#                         "knn": {
#                             "emb_audio": {
#                                 "vector": query_embedding,
#                                 "k": INNER_TOP_K
#                             }
#                         }
#                     },
#                     # Transcription embedding (k-NN) - weight 0.5
#                     {
#                         "knn": {
#                             "emb_transcription": {
#                                 "vector": query_embedding,
#                                 "k": INNER_TOP_K
#                             }
#                         }
#                     }
#                 ]
#             }
#         },
#         "_source": ["video_id", "video_path", "clip_id", "timestamp_start",
#                    "timestamp_end", "clip_text", "thumbnail_path", "video_name", "clip_duration", "video_duration_sec"]
#     }

#     if vector_pipeline_exists:
#         search_params = {
#                 "index": INDEX_NAME,
#                 "body": search_body,
#                 "search_pipeline": selected_pipeline  # Using preference-based pipeline
#             }
#     else:
#         search_params = {
#                 "index": INDEX_NAME,
#                 "body": search_body
#             }

#     try:
#         response = client.search(**search_params)
#         logger.info(f"✓ Vector search (audio+transcription {preference}, Marengo 3) completed, found {len(response.get('hits', {}).get('hits', []))} results")
#         return parse_search_results_vector(response)
#     except Exception as e:
#         logger.error(f"Vector search (audio+transcription, Marengo 3) error: {e}", exc_info=True)
#         return []


def _create_hybrid_search_pipeline(client):
    """Create search pipeline with score normalization for hybrid search"""

    pipeline_body = {
        "description": "Post-processing pipeline for hybrid search with normalization",
        "phase_results_processors": [
            {
                "normalization-processor": {
                    "normalization": {"technique": "min_max"},
                    "combination": {
                        "technique": "arithmetic_mean",
                        "parameters": {"weights": [0.5, 0.3, 0.2]},
                    },
                }
            }
        ],
    }

    try:
        client.search_pipeline.put(
            id="hybrid-norm-pipeline-consolidated-index", body=pipeline_body
        )
        logger.info("✓ Created hybrid search pipeline with min-max normalization")

    except Exception as e:
        logger.warning(f"✗ Pipeline creation error: {e}")
        return False

    return True


def _create_vector_search_pipeline(client):
    """Create search pipeline with score normalization for vector search"""

    # pipeline_body = {
    #     "description": "Post-processing pipeline for vector search with min-max normalization (0-1 range)",
    #     "phase_results_processors": [
    #         {
    #             "normalization-processor": {
    #                 "normalization": {
    #                     "technique": "min_max"
    #                 },
    #                 "combination": {
    #                     "technique": "arithmetic_mean",
    #                     "parameters": {
    #                         "weights": [0.6, 0.4]
    #                     }
    #                 }
    #             }
    #         }
    #     ]
    # }

    pipeline_body = {
        "description": "Post processor for hybrid RRF search",
        "phase_results_processors": [
            {
                "score-ranker-processor": {
                    "combination": {"technique": "rrf", "rank_constant": 60}
                }
            }
        ],
    }

    # pipeline_body = {
    #     "description": "Post-processing pipeline for vector search with min-max normalization (0-1 range)",
    #     "phase_results_processors": [
    #         {
    #             "normalization-processor": {
    #                 "normalization": {
    #                     "technique": "l2"
    #                 },
    #                 "combination": {
    #                     "technique": "arithmetic_mean"
    #                 }
    #             }
    #         }
    #     ]
    # }

    try:
        client.search_pipeline.put(id=VECTOR_PIPELINE, body=pipeline_body)
        logger.info("✓ Created vector search pipeline with normalization")

    except Exception as e:
        logger.warning(f"✗ Vector pipeline creation error: {e}")
        return False

    return True


def _create_intent_based_pipelines(client):
    """Create intent-based search pipelines with different RRF weights for Marengo 3"""

    intent_pipelines = {
        "VISUAL": VECTOR_PIPELINE_3_VISUAL,
        "AUDIO": VECTOR_PIPELINE_3_AUDIO,
        "TRANSCRIPT": VECTOR_PIPELINE_3_TRANSCRIPT,
        "BALANCED": VECTOR_PIPELINE_3_BALANCED,
    }

    for intent, pipeline_id in intent_pipelines.items():
        weights = INTENT_WEIGHTS[intent]

        pipeline_body = {
            "description": f"Post processor for hybrid RRF search with {intent} intent weights",
            "phase_results_processors": [
                {
                    "score-ranker-processor": {
                        "combination": {
                            "technique": "rrf",
                            "rank_constant": 60,
                            "parameters": {"weights": weights},
                        }
                    }
                }
            ],
        }

        try:
            client.search_pipeline.put(id=pipeline_id, body=pipeline_body)
            logger.info(
                f"✓ Created {intent} intent search pipeline: {pipeline_id} with weights {weights}"
            )
        except Exception as e:
            logger.warning(f"✗ {intent} intent pipeline creation error: {e}")


def _create_combination_pipelines(client):
    """Create combination search pipelines with RRF weights for 2-modality searches (Marengo 3)
    Creates 9 pipelines total: 3 variants (visual-focus, audio/text-focus, balanced) for each of 3 combinations
    """
    
    # Define all 9 combination pipelines with their weights
    combination_pipelines = {
        # Visual_Audio variants
        "VISUAL_AUDIO_VISUAL_FOCUS": (VECTOR_PIPELINE_3_VISUAL_AUDIO_VISUAL_FOCUS, COMBINATION_WEIGHTS["VISUAL_AUDIO_VISUAL_FOCUS"]),
        "VISUAL_AUDIO_AUDIO_FOCUS": (VECTOR_PIPELINE_3_VISUAL_AUDIO_AUDIO_FOCUS, COMBINATION_WEIGHTS["VISUAL_AUDIO_AUDIO_FOCUS"]),
        "VISUAL_AUDIO_BALANCED": (VECTOR_PIPELINE_3_VISUAL_AUDIO_BALANCED, COMBINATION_WEIGHTS["VISUAL_AUDIO_BALANCED"]),
        
        # # Visual_Transcription variants
        # "VISUAL_TRANSCRIPTION_VISUAL_FOCUS": (VECTOR_PIPELINE_3_VISUAL_TRANSCRIPTION_VISUAL_FOCUS, COMBINATION_WEIGHTS["VISUAL_TRANSCRIPTION_VISUAL_FOCUS"]),
        # "VISUAL_TRANSCRIPTION_TEXT_FOCUS": (VECTOR_PIPELINE_3_VISUAL_TRANSCRIPTION_TEXT_FOCUS, COMBINATION_WEIGHTS["VISUAL_TRANSCRIPTION_TEXT_FOCUS"]),
        # "VISUAL_TRANSCRIPTION_BALANCED": (VECTOR_PIPELINE_3_VISUAL_TRANSCRIPTION_BALANCED, COMBINATION_WEIGHTS["VISUAL_TRANSCRIPTION_BALANCED"]),
        
        # # Audio_Transcription variants
        # "AUDIO_TRANSCRIPTION_AUDIO_FOCUS": (VECTOR_PIPELINE_3_AUDIO_TRANSCRIPTION_AUDIO_FOCUS, COMBINATION_WEIGHTS["AUDIO_TRANSCRIPTION_AUDIO_FOCUS"]),
        # "AUDIO_TRANSCRIPTION_TEXT_FOCUS": (VECTOR_PIPELINE_3_AUDIO_TRANSCRIPTION_TEXT_FOCUS, COMBINATION_WEIGHTS["AUDIO_TRANSCRIPTION_TEXT_FOCUS"]),
        # "AUDIO_TRANSCRIPTION_BALANCED": (VECTOR_PIPELINE_3_AUDIO_TRANSCRIPTION_BALANCED, COMBINATION_WEIGHTS["AUDIO_TRANSCRIPTION_BALANCED"]),
    }

    for combination_name, (pipeline_id, weights) in combination_pipelines.items():
        pipeline_body = {
            "description": f"Post processor for hybrid RRF search with {combination_name} weights",
            "phase_results_processors": [
                {
                    "score-ranker-processor": {
                        "combination": {
                            "technique": "rrf",
                            "rank_constant": 60,
                            "parameters": {"weights": weights},
                        }
                    }
                }
            ],
        }

        try:
            client.search_pipeline.put(id=pipeline_id, body=pipeline_body)
            logger.info(
                f"✓ Created {combination_name} pipeline: {pipeline_id} with weights {weights}"
            )
        except Exception as e:
            logger.warning(f"✗ {combination_name} pipeline creation error: {e}")


def _create_vector_search_pipeline_3_vector(client):
    """Create search pipeline with score normalization for vector search"""

    pipeline_body = {
        "description": "Post processor for hybrid RRF search",
        "phase_results_processors": [
            {
                "score-ranker-processor": {
                    "combination": {
                        "technique": "rrf",
                        "rank_constant": 60,
                        "parameters": {"weights": [0.5, 0.4, 0.1]},
                    }
                }
            }
        ],
    }

    try:
        client.search_pipeline.put(id=VECTOR_PIPELINE_3_VECTOR, body=pipeline_body)
        logger.info("✓ Created marengo-3-vector search pipeline with normalization")

    except Exception as e:
        logger.warning(f"✗ Vector pipeline creation error: {e}")
        return False

    return True


def parse_search_results(response: Dict) -> List[Dict]:
    """Parse OpenSearch response into results list"""
    results = []

    for hit in response["hits"]["hits"]:
        result = hit["_source"]
        result["score"] = hit["_score"]
        result["_id"] = hit["_id"]
        # logger.info(result)
        results.append(result)

    return results


# def parse_search_results_vector(response: Dict) -> List[Dict]:
#     """Parse OpenSearch results and apply L2 score normalization (optimized)."""
#     results = []
#     sum_sq = 0.0

#     # First loop: collect results & accumulate squared scores
#     for hit in response['hits']['hits']:
#         result = hit['_source']

#         score = hit['_score']
#         sum_sq += score * score

#         result['score'] = score
#         result['_id'] = hit['_id']
#         results.append(result)

#     print(results)

#     # Compute L2 norm
#     norm = math.sqrt(sum_sq) if sum_sq > 0 else 1.0
#     logger.info(f"L2 norm: {norm}")
#     # Second loop: apply normalized score
#     for r in results:
#         r['score'] = r['score'] / norm

#     print(results)

#     return results

# def parse_search_results_vector(response: Dict) -> List[Dict]:
#     """Parse OpenSearch results and apply min-max score normalization."""
#     results = []
#     scores = []

#     # First loop: collect results & raw scores
#     for hit in response['hits']['hits']:
#         result = hit['_source']
#         score = hit['_score']

#         result['score'] = score
#         result['_id'] = hit['_id']

#         results.append(result)
#         scores.append(score)

#     print(results)

#     # Compute min and max
#     if scores:
#         mn = min(scores)
#         mx = max(scores)
#     else:
#         mn, mx = 0.0, 1.0

#     logger.info(f"Min score: {mn}, Max score: {mx}")

#     # Avoid division-by-zero: if all scores equal
#     denom = mx - mn if mx != mn else 1.0

#     # Second loop: apply min-max normalization
#     for r in results:
#         r['score'] = (r['score'] - mn) / denom

#     print(results)

#     return results

# def sigmoid(x: float) -> float:
#     return 1.0 / (1.0 + math.exp(-x))

# def parse_search_results_vector(response: Dict) -> List[Dict]:
#     """Parse OpenSearch results and apply sigmoid normalization to scores."""
#     results = []
#     scores = []

#     # First loop: collect results & raw scores
#     for hit in response['hits']['hits']:
#         result = hit['_source']
#         score = hit['_score']

#         result['_id'] = hit['_id']
#         result['score_raw'] = score

#         results.append(result)
#         scores.append(score)

#     # Compute mean for centering (b)
#     if scores:
#         mean_score = sum(scores) / len(scores)
#     else:
#         mean_score = 0.0

#     final_results = []
#     # Steepness factor
#     a = 5.0   # Feel free to tune this (3–10)
#     scale = 100.0/2
#     # print(results)
#     # Apply sigmoid normalization
#     for r in results:
#         centered = (r['score_raw'] - mean_score) * scale
#         r['score'] = sigmoid(a * centered)
#         if r['score'] < MIN_SCORE:
#             break
#         final_results.append(r)

#     # print(final_results)
#     return final_results


def _apply_category_filter(search_body: dict, categories: Optional[List[str]]) -> dict:
    """Wrap an existing OpenSearch query in a bool+filter to pre-filter by categories."""
    if not categories:
        return search_body
    original_query = search_body["query"]
    search_body["query"] = {
        "bool": {
            "must": [original_query],
            "filter": [{"terms": {"categories": categories}}]
        }
    }
    logger.info(f"📂 Applied category pre-filter: {categories}")
    return search_body


def _apply_advanced_filters(
    search_body: dict,
    categories: Optional[List[str]] = None,
    min_relevance: Optional[float] = None,
    max_segments_per_video: Optional[int] = None
) -> dict:
    """
    Apply advanced filters to OpenSearch query for efficient server-side filtering.
    
    CRITICAL FIXES for OpenSearch 3.3 compatibility:
    1. Category filter uses hybrid's native filter parameter (not bool wrapping)
    2. min_relevance is applied CLIENT-SIDE after search (not server-side)
    3. max_segments_per_video is applied CLIENT-SIDE after search (collapse doesn't work with RRF)
    
    Filters applied:
    1. Category pre-filter - Uses hybrid.filter parameter (preserves normalization pipeline)
    2. Min relevance score - APPLIED CLIENT-SIDE after search with normalized scores
    3. Max segments per video - APPLIED CLIENT-SIDE after search (collapse incompatible with RRF)
    
    Args:
        search_body: The OpenSearch query body to modify (must contain hybrid query)
        categories: List of category values to filter by (OR logic)
        min_relevance: Minimum score threshold - APPLIED CLIENT-SIDE (not used here)
        max_segments_per_video: Maximum segments per video - APPLIED CLIENT-SIDE (not used here)
    
    Returns:
        Modified search_body with filters applied
    """
    
    # 1. Category filter — use hybrid's native filter param, NOT bool wrapping
    # Wrapping hybrid in bool.must breaks the normalization pipeline
    if categories:
        # Check if this is a hybrid query
        if "hybrid" in search_body.get("query", {}):
            search_body["query"]["hybrid"]["filter"] = {
                "terms": {"categories": categories}
            }
            logger.info(f"📂 Applied category pre-filter to hybrid query: {categories}")
    
    # 2. min_relevance — NOT applied here, handled client-side after search
    # This ensures we work with normalized scores from RRF pipeline
    
    # 3. max_segments_per_video — NOT applied here, handled client-side after search
    # Collapse doesn't work properly with RRF pipelines, so we handle it post-search
    # This ensures proper score normalization and segment selection
    if max_segments_per_video is not None and max_segments_per_video > 0:
        # Increase size to get more results for post-processing
        search_body["size"] = search_body.get("size", TOP_K) * 3
        logger.info(f"📊 Increased query size for post-search collapse: max {max_segments_per_video} segments per video")
    
    return search_body


def apply_post_filters(results: List[Dict], min_relevance: Optional[float] = None, max_segments_per_video: Optional[int] = None) -> List[Dict]:
    """
    Post-process search results with client-side filtering and collapsing.
    
    For vector/hybrid searches, this uses normalized RRF scores (0.0-1.0 range)
    from parse_search_results_vector().
    
    Args:
        results: Search results with normalized scores
        min_relevance: Minimum normalized score threshold (0.0-1.0)
        max_segments_per_video: Maximum segments to return per unique video_id
    
    Returns:
        Filtered and collapsed results
    """
    # Min relevance filter - uses normalized scores from parse_search_results_vector()
    if min_relevance is not None:
        before_count = len(results)
        results = [r for r in results if r.get("score", 0) >= min_relevance]
        logger.info(f"📊 Client-side min_relevance filter ({min_relevance}): {before_count} → {len(results)} results")

    # Max segments per video - collapse by video_id (post-search)
    if max_segments_per_video is not None and max_segments_per_video > 0:
        before_count = len(results)
        video_segments = {}
        
        # Group results by video_id and keep top N segments per video
        for result in results:
            video_id = result.get("video_id")
            if video_id not in video_segments:
                video_segments[video_id] = []
            
            # Only add if we haven't reached the limit for this video
            if len(video_segments[video_id]) < max_segments_per_video:
                video_segments[video_id].append(result)
        
        # Flatten back to a single list, maintaining score order
        results = []
        for segments in video_segments.values():
            results.extend(segments)
        
        # Re-sort by score to maintain relevance order
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        
        logger.info(f"📊 Client-side max_segments_per_video collapse ({max_segments_per_video}): {before_count} → {len(results)} results")

    return results


def normalize_rrf(rrf_raw, M=1.23, k=60):
    rrf_max = M * (1.0 / (k + 1.0))  # = ~0.03278688 when M=2
    return min(1.0, rrf_raw / rrf_max)


def parse_search_results_vector(response):
    results = []

    for hit in response["hits"]["hits"]:
        raw = hit["_score"]

        result = hit["_source"]
        result["_id"] = hit["_id"]
        result["score_raw"] = raw
        result["score"] = round(normalize_rrf(raw), 3)

        results.append(result)

    # print(results)

    return results


def parse_search_results_with_collapse(response: Dict, max_segments: int) -> List[Dict]:
    """
    Parse OpenSearch response with collapse feature and normalize RRF scores.
    Extracts top segments from inner_hits for each collapsed video.
    Applies same RRF normalization as parse_search_results_vector().
    """
    results = []
    
    for hit in response["hits"]["hits"]:
        # Get the top segment for this video (the collapsed hit)
        raw_score = hit["_score"]
        main_result = hit["_source"]
        main_result["_id"] = hit["_id"]
        main_result["score_raw"] = raw_score
        main_result["score"] = round(normalize_rrf(raw_score), 3)  # Normalize RRF score
        results.append(main_result)
        
        # Get additional segments from inner_hits if available
        if "inner_hits" in hit and "top_segments" in hit["inner_hits"]:
            inner_hits = hit["inner_hits"]["top_segments"]["hits"]["hits"]
            for inner_hit in inner_hits[1:]:  # Skip first one as it's the main result
                inner_raw_score = inner_hit["_score"]
                inner_result = inner_hit["_source"]
                inner_result["_id"] = inner_hit["_id"]
                inner_result["score_raw"] = inner_raw_score
                inner_result["score"] = round(normalize_rrf(inner_raw_score), 3)  # Normalize RRF score
                results.append(inner_result)
    
    logger.info(f"📊 Extracted {len(results)} segments from collapsed results (scores normalized)")
    return results


# def _configure_s3_cors(s3_client):
#     """Configure restrictive CORS policy on S3 bucket for video uploads"""
#     bucket_name = os.environ.get('AWS_S3_BUCKET')
#     if not bucket_name:
#         logger.warning("AWS_S3_BUCKET not set, skipping CORS configuration")
#         return

#     cors_config = {
#         'CORSRules': [
#             {
#                 'AllowedOrigins': [
#                     'http://localhost:3000',
#                     'http://demo-fe.s3-website-us-east-1.amazonaws.com',
#                     'https://demo-fe.s3-website-us-east-1.amazonaws.com'
#                 ],
#                 'AllowedMethods': ['PUT', 'POST', 'GET', 'HEAD'],
#                 'AllowedHeaders': ['*'],
#                 'MaxAgeSeconds': 3000,
#                 'ExposeHeaders': ['ETag', 'x-amz-version-id']
#             }
#         ]
#     }

#     try:
#         s3_client.put_bucket_cors(Bucket=bucket_name, CORSConfiguration=cors_config)
#         logger.info(f"✓ S3 CORS policy configured for bucket: {bucket_name}")
#     except Exception as e:
#         logger.warning(f"Could not configure S3 CORS (may require manual setup): {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
