import os

import uvicorn
import boto3
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import services
from routes import router
from pymongo import MongoClient
from opensearchpy import OpenSearch, RequestsHttpConnection, AWSV4SignerAuth

_enable_docs = True

app = FastAPI(
    title="Video Search Service",
    version="1.0.0",
    docs_url="/docs" if _enable_docs else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    # Initialize all external clients here (single source of truth).
    strict_startup = os.environ.get("STRICT_STARTUP", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }

    if not os.environ.get("OPENSEARCH_CLUSTER_HOST"):
        # Keep the app up, but endpoints that require clients will return 503.
        return

    try:
        app.state.opensearch_client = get_opensearch_client()
        app.state.bedrock_runtime = boto3.client("bedrock-runtime", region_name="us-east-1")
        app.state.s3_client = boto3.client("s3", region_name="us-east-1")
        docdb_uri, _docdb_db_name, _docdb_users_collection = services.get_docdb_settings()

        tls_ca_file = "/app/global-bundle.pem" if os.path.exists("/app/global-bundle.pem") else None
        app.state.docdb_client = MongoClient(
            docdb_uri,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000,
            tlsCAFile=tls_ca_file,
        )

        # Initialize OpenSearch pipelines (idempotent).
        services.hybrid_pipeline_exists = services._create_hybrid_search_pipeline(
            app.state.opensearch_client
        )
        services.vector_pipeline_exists = services._create_vector_search_pipeline(
            app.state.opensearch_client
        )
        services._create_vector_search_pipeline_3_vector(app.state.opensearch_client)
        services._create_combination_pipelines(app.state.opensearch_client)

        # Verify DocumentDB connectivity early.
        app.state.docdb_client.admin.command("ping")
        services.logger.info("DocumentDB connectivity verified")

    except Exception:
        app.state.opensearch_client = None
        app.state.bedrock_runtime = None
        app.state.s3_client = None
        app.state.docdb_client = None
        if strict_startup:
            raise


app.include_router(router)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

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