import asyncio
import datetime
import math
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, validator
from pymongo.errors import PyMongoError

from services import *
from services import (
    _average_vectors,
    _create_access_token,
    _get_user_sub,
    _s3_key_to_base64_image,
    _s3_key_to_presigned_url,
)

router = APIRouter()


def _get_app_clients(request: Request) -> Dict[str, Any]:
    app = request.app
    return {
        "opensearch": getattr(app.state, "opensearch_client", None),
        "bedrock": getattr(app.state, "bedrock_runtime", None),
        "s3": getattr(app.state, "s3_client", None),
        "docdb": getattr(app.state, "docdb_client", None),
    }


def _ensure_clients_ready(clients: Dict[str, Any]) -> None:
    if clients.get("opensearch") is None or clients.get("bedrock") is None or clients.get("s3") is None:
        raise HTTPException(status_code=503, detail="Search service not initialized")


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, str]


class EntityCreateRequest(BaseModel):
    """
    Request body for creating a new person/entity.
    The client must upload images to S3 first and then send the S3 keys here,
    along with an explicit primary_image_key which will always be used for search.
    """

    name: str
    image_keys: List[str]
    primary_image_key: str

    @validator("name")
    def validate_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("name is required")
        if len(v) > 200:
            raise ValueError("name must be <= 200 characters")
        return v

    @validator("image_keys")
    def validate_image_keys(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("at least one image key is required")
        if len(v) > 10:
            raise ValueError("no more than 10 images are allowed per entity")
        cleaned = [s.strip() for s in v if s and s.strip()]
        if not cleaned:
            raise ValueError("at least one non-empty image key is required")
        return cleaned

    @validator("primary_image_key")
    def validate_primary_key(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("primary_image_key is required")
        return v


class EntityListItem(BaseModel):
    entity_id: str
    name: str
    thumbnail_url: Optional[str] = None


class EntityListResponse(BaseModel):
    entities: List[EntityListItem]


class SearchRequest(BaseModel):
    query_text: Optional[str] = None
    image_base64: Optional[str] = None
    # When provided, search will use this saved entity as the visual anchor.
    # The primary image configured for the entity will always be used for entity-based search.
    entity_id: Optional[str] = None
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


class CompleteMultipartRequest(BaseModel):
    """Request body for completing multipart upload"""
    uploadId: str
    s3_key: str
    # Accept PartNumber as int (or string coercible to int) and validate shape.
    class Part(BaseModel):
        ETag: str
        PartNumber: int

    parts: List[Part]


@router.post("/auth/login", response_model=LoginResponse)
async def auth_login(body: LoginRequest, request: Request):
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

    clients = _get_app_clients(request)
    docdb_client = clients.get("docdb")
    if docdb_client is None:
        raise HTTPException(status_code=503, detail="Auth service unavailable")

    def _docdb_check(username_value: str, plain_password: str) -> Dict[str, str]:
        docdb_client.admin.command("ping")
        _uri, db_name, users_collection_name = get_docdb_settings()
        db = docdb_client[db_name]
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


@router.get("/health")
async def health_check():
    """Health check endpoint for ECS task"""
    return {"status": "healthy", "service": "video-search"}


@router.post("/search", response_model=SearchResponse)
async def search_videos(
    request: SearchRequest,
    http_request: Request,
    _auth: Dict[str, Any] = Depends(require_auth),
):
    """
    Unified search endpoint - handles both text and image searches
    - Text search: Uses query_text with specified search_type
    - Image search: Uses image_base64, generates embedding, performs image-specific search
    """
    try:
        clients = _get_app_clients(http_request)
        _ensure_clients_ready(clients)
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
            query_embedding = generate_image_embedding(clients["bedrock"], image_base64)

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
                clients["opensearch"], query_embedding, top_k, INDEX_NAME
            )

            query_display = ""  # Empty query for image search
            search_type_display = "image"

        # TRANSCRIPT SEARCH PATH
        else:
            logger.info(
                f"🔍 Text search: '{query_text}' (type: {search_type}, top_k: {top_k})"
            )
            logger.info("Generating embedding from text using Marengo")
            query_embedding = generate_text_embedding(clients["bedrock"], str(query_text))

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
                    clients["opensearch"],
                    query_embedding,
                    str(query_text),
                    top_k,
                    INDEX_NAME,
                )
            elif search_type == "vector":
                results = vector_search(
                    clients["opensearch"], query_embedding, top_k, INDEX_NAME
                )
            elif search_type == "visual":
                results = visual_search(
                    clients["opensearch"], query_embedding, top_k, INDEX_NAME
                )
            elif search_type == "audio":
                results = audio_search(
                    clients["opensearch"], query_embedding, top_k, INDEX_NAME
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
        results = convert_s3_to_presigned_urls(clients["s3"], results)

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


@router.post("/search-3", response_model=SearchResponse)
async def search_videos_marengo3(
    request: SearchRequest,
    http_request: Request,
    _auth: Dict[str, Any] = Depends(require_auth),
):
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
        clients = _get_app_clients(http_request)
        _ensure_clients_ready(clients)
        query_text = request.query_text
        image_base64 = request.image_base64
        entity_id = request.entity_id
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
        if not query_text and not image_base64 and not entity_id:
            raise HTTPException(
                status_code=400, detail="Either query_text, image_base64, or entity_id is required"
            )

        # Entity-based search: always use the configured primary image for this entity
        search_input_type = "text"
        classified_intent = None
        query_embedding: Optional[List[float]] = None

        if entity_id:
            if image_base64:
                raise HTTPException(
                    status_code=400,
                    detail="image_base64 must not be provided when searching by entity_id",
                )

            user_sub = _get_user_sub(_auth)
            if clients.get("docdb") is None:
                raise HTTPException(status_code=503, detail="Entities service unavailable")
            _, db_name, _users_collection = get_docdb_settings()
            entities_coll = clients["docdb"][db_name]["entities"]
            entity_doc = entities_coll.find_one({"user_sub": user_sub, "entity_id": entity_id})
            if not entity_doc:
                raise HTTPException(status_code=404, detail="Entity not found")

            primary_key = str(
                entity_doc.get("primary_image_key")
                or (entity_doc.get("image_keys") or [None])[0]
            )
            if not primary_key:
                raise HTTPException(
                    status_code=500,
                    detail="Entity is missing primary_image_key and image_keys",
                )

            # Case 1: entity only (no text) -> use stored or freshly computed primary embedding
            if not query_text:
                stored_embedding = entity_doc.get("primary_embedding")
                if stored_embedding and isinstance(stored_embedding, list) and stored_embedding:
                    query_embedding = stored_embedding
                    search_input_type = "entity_image"
                    classified_intent = "VISUAL_FOCUS"
                    logger.info(
                        f"Using cached primary embedding for entity_id={entity_id} (len={len(stored_embedding)})"
                    )
                else:
                    logger.info(
                        f"Generating primary image embedding for entity_id={entity_id} using its primary image"
                    )
                    img_b64 = _s3_key_to_base64_image(clients["s3"], primary_key)
                    embedding = generate_embedding_marengo3(
                        clients["bedrock"], text=None, image_base64=img_b64
                    )
                    if not embedding:
                        raise HTTPException(
                            status_code=500,
                            detail="Failed to generate embedding for entity primary image",
                        )
                    query_embedding = embedding
                    search_input_type = "entity_image"
                    classified_intent = "VISUAL_FOCUS"

                    # Best effort: cache embedding back into the document
                    try:
                        entities_coll.update_one(
                            {"_id": entity_doc["_id"]},
                            {"$set": {"primary_embedding": embedding}},
                        )
                    except Exception as e:
                        logger.warning(
                            f"Failed to cache primary_embedding for entity_id={entity_id}: {e}"
                        )
            # Case 2: entity + text -> multimodal text+image embedding, using primary image
            else:
                logger.info(
                    f"🔄 Multimodal entity search (Marengo 3): text + primary image for entity_id={entity_id}"
                )
                img_b64 = _s3_key_to_base64_image(clients["s3"], primary_key)
                query_embedding = generate_embedding_marengo3(
                    clients["bedrock"], text=query_text, image_base64=img_b64
                )
                search_input_type = "entity_multimodal"
                classified_intent = "VISUAL_FOCUS"

                logger.info(
                    f"✓ Generated {search_input_type} embedding (Marengo 3) with {len(query_embedding) if query_embedding else 0} dimensions"
                )

        else:
            # Non-entity search: existing text/image/multimodal logic
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
                intent_task = detect_visual_audio_focus_llm(clients["bedrock"], query_text)
                embedding_task = asyncio.to_thread(
                    generate_embedding_marengo3,
                    clients["bedrock"],
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
                    clients["bedrock"], text=query_text, image_base64=image_base64
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
                clients["opensearch"], query_embedding, top_k, "video_clips_3_lucene", 
                preference = classified_intent if classified_intent else "BALANCED", 
                categories=categories, min_relevance=min_relevance, max_segments_per_video=max_segments_per_video
            )
        elif search_type == "vector":
            # Using balanced vector search (all 3 modalities)
            logger.info("📊 Using balanced vector search (all 3 modalities)")
            results = vector_search_marengo3(
                clients["opensearch"], query_embedding, top_k, "video_clips_3_lucene", 
                preference = classified_intent if classified_intent else "BALANCED", 
                categories=categories, min_relevance=min_relevance, max_segments_per_video=max_segments_per_video
            )
        elif search_type == "visual":
            results = visual_search_marengo3(
                clients["opensearch"], query_embedding, top_k, "video_clips_3_lucene", 
                categories=categories, min_relevance=min_relevance, max_segments_per_video=max_segments_per_video
            )
        elif search_type == "audio":
            results = audio_search_marengo3(
                clients["opensearch"], query_embedding, top_k, "video_clips_3_lucene", 
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
        results = convert_s3_to_presigned_urls(clients["s3"], results)

        logger.info(f"✓ Search (Marengo 3) completed, found {len(results)} results")

        # Retrieve actual weights from OpenSearch pipeline configuration
        weights_used = []
        if classified_intent and classified_intent in intent_pipeline_map:
            try:
                pipeline_id = intent_pipeline_map[classified_intent]
                pipeline_response = clients["opensearch"].search_pipeline.get(id=pipeline_id)

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


@router.get("/entities", response_model=EntityListResponse)
async def list_entities(http_request: Request, _auth: Dict[str, Any] = Depends(require_auth)):
    """
    List entities saved by the authenticated user.
    Used by the frontend @-mention dropdown.
    """
    try:
        clients = _get_app_clients(http_request)
        _ensure_clients_ready(clients)
        if clients.get("docdb") is None:
            raise HTTPException(status_code=503, detail="Entities service unavailable")
        user_sub = _get_user_sub(_auth)

        _, db_name, _users_collection = get_docdb_settings()
        entities_coll = clients["docdb"][db_name]["entities"]
        docs = list(entities_coll.find({"user_sub": user_sub}).sort("created_at", -1))

        bucket_thumbnail = os.environ.get("AWS_S3_BUCKET")
        entities: List[EntityListItem] = []
        for doc in docs:
            primary_key = doc.get("primary_image_key")
            thumbnail_url = (
                _s3_key_to_presigned_url(clients["s3"], primary_key, expiration=3600)
                if primary_key and bucket_thumbnail
                else None
            )
            entities.append(
                EntityListItem(
                    entity_id=str(doc.get("entity_id") or ""),
                    name=str(doc.get("name") or ""),
                    thumbnail_url=thumbnail_url,
                )
            )

        return EntityListResponse(entities=entities)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in list_entities: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/entities", response_model=EntityListItem)
async def create_entity(
    request: EntityCreateRequest,
    http_request: Request,
    _auth: Dict[str, Any] = Depends(require_auth),
):
    """
    Create a new entity (person) from reference images.
    The client must explicitly provide `primary_image_key`, which is ALWAYS used for searching.
    """
    try:
        clients = _get_app_clients(http_request)
        _ensure_clients_ready(clients)
        if clients.get("docdb") is None:
            raise HTTPException(status_code=503, detail="Entities service unavailable")
        user_sub = _get_user_sub(_auth)

        primary_key = request.primary_image_key
        image_keys = request.image_keys

        if primary_key not in image_keys:
            raise HTTPException(
                status_code=400,
                detail="primary_image_key must be one of image_keys",
            )

        if len(image_keys) < 1 or len(image_keys) > 10:
            raise HTTPException(
                status_code=400,
                detail="Entities must have between 1 and 10 reference images.",
            )

        # Compute embeddings for each reference image.
        embeddings: List[List[float]] = []
        primary_embedding: Optional[List[float]] = None

        for s3_key in image_keys:
            img_b64 = _s3_key_to_base64_image(clients["s3"], s3_key)
            embedding = generate_embedding_marengo3(
                clients["bedrock"], text=None, image_base64=img_b64
            )
            if not embedding:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to generate embedding for entity image key: {s3_key}",
                )
            embeddings.append(embedding)
            if s3_key == primary_key:
                primary_embedding = embedding

        if not primary_embedding:
            raise HTTPException(status_code=500, detail="Failed to compute primary embedding")

        prototype_embedding = _average_vectors(embeddings)

        entity_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc)

        doc = {
            "user_sub": user_sub,
            "entity_id": entity_id,
            "name": request.name,
            "image_keys": image_keys,
            "primary_image_key": primary_key,
            "primary_embedding": primary_embedding,
            "prototype_embedding": prototype_embedding,
            "created_at": now,
            "updated_at": now,
        }

        _, db_name, _users_collection = get_docdb_settings()
        entities_coll = clients["docdb"][db_name]["entities"]
        entities_coll.insert_one(doc)

        thumbnail_url = _s3_key_to_presigned_url(clients["s3"], primary_key, expiration=3600)

        return EntityListItem(entity_id=entity_id, name=request.name, thumbnail_url=thumbnail_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create_entity: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list", response_model=VideosListResponse)
async def list_all_videos(http_request: Request, _auth: Dict[str, Any] = Depends(require_auth)):
    """
    Get all unique videos from the OpenSearch index
    Returns video metadata including S3 paths and clip counts
    """
    try:
        clients = _get_app_clients(http_request)
        _ensure_clients_ready(clients)
        # Get all unique videos from OpenSearch
        videos = get_all_unique_videos(clients["opensearch"])

        # Transform to response format
        video_list = []
        for video in videos:
            # Generate presigned URL for private S3 bucket access
            presigned_url = convert_s3_to_presigned_url(clients["s3"], video["video_path"])

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


@router.post("/generate-upload-presigned-url")
async def generate_upload_url(
    filename: str,
    file_size: int = None,
    category: Optional[str] = None,
    content_type: Optional[str] = None,
    http_request: Request = None,
    _auth: Dict[str, Any] = Depends(require_auth),
):
    """
    Generate presigned URLs for S3 upload from frontend
    - For files < 100MB: Single PUT upload
    - For files >= 100MB: Multipart upload with multiple presigned URLs
    """
    try:
        clients = _get_app_clients(http_request)
        _ensure_clients_ready(clients)
        if clients["s3"] is None:
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

        # Normalize content type (if provided) so it can be safely signed.
        # If we sign ContentType for a presigned PUT, the uploader must send the exact same header
        # or S3 will return 403 SignatureDoesNotMatch.
        normalized_content_type = (content_type or "").strip() or None

        # CASE 1: SINGLE PUT (files < 100MB)
        if file_size is None or file_size < MULTIPART_THRESHOLD:
            logger.info(f"Single PUT upload for: {s3_key} (size: {file_size or 'unknown'})")
            
            put_params: Dict[str, Any] = {"Bucket": bucket_name, "Key": s3_key}
            if normalized_content_type:
                put_params["ContentType"] = normalized_content_type

            presigned_url = clients["s3"].generate_presigned_url(
                "put_object",
                Params=put_params,
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
            create_params: Dict[str, Any] = {"Bucket": bucket_name, "Key": s3_key}
            if normalized_content_type:
                create_params["ContentType"] = normalized_content_type
            multipart_response = clients["s3"].create_multipart_upload(**create_params)
            upload_id = multipart_response["UploadId"]
            logger.info(f"✓ Initiated multipart upload with ID: {upload_id}")

            # Calculate number of parts needed
            num_parts = math.ceil(file_size / CHUNK_SIZE)
            logger.info(f"Generating {num_parts} presigned URLs for {num_parts} parts")

            # Generate presigned URLs for each part
            presigned_urls = []
            for part_num in range(1, num_parts + 1):
                presigned_url = clients["s3"].generate_presigned_url(
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


@router.post("/complete-multipart-upload")
async def complete_multipart_upload(
    request: CompleteMultipartRequest,
    http_request: Request,
    _auth: Dict[str, Any] = Depends(require_auth),
):
    """
    Complete a multipart S3 upload after all parts have been uploaded
    """
    try:
        clients = _get_app_clients(http_request)
        _ensure_clients_ready(clients)
        if clients["s3"] is None:
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
            response = clients["s3"].complete_multipart_upload(
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

        except clients["s3"].exceptions.NoSuchUpload:
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

