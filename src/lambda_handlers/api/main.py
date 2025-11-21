from fastapi import FastAPI
from mangum import Mangum

import routes.events as events
import routes.health as health

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
