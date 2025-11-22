from fastapi import FastAPI
from mangum import Mangum

from .routes import events, health

app = FastAPI(
    title="Trigger Ingestion API",
    description="Multi-tenant event ingestion API",
    version="1.0.0"
)

# Include routers
app.include_router(health.router)
app.include_router(events.router)

# Mangum handler for AWS Lambda
handler = Mangum(app)
