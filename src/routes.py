from fastapi import FastAPI
from src.auth.controller import router as auth_router
from src.users.controller import router as users_router
from src.domains.controller import router as domains_router
from src.ingestion.controller import router as ingestion_router
from src.chunking.controller import ingestion_config_router, chunks_router
from src.ontology.controller import router as ontology_router
from src.extraction.controller import router as graph_router
from src.retrieval.controller import retrieval_config_router, query_router

def register_routes(app: FastAPI):
    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(domains_router)
    app.include_router(ingestion_router)
    app.include_router(ingestion_config_router)
    app.include_router(chunks_router)
    app.include_router(ontology_router)
    app.include_router(graph_router)
    app.include_router(retrieval_config_router)
    app.include_router(query_router)
