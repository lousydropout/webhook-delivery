from fastapi import FastAPI
from mangum import Mangum
from routes import router

app = FastAPI(
    title="Webhook Delivery API",
    description="Multi-tenant webhook delivery system",
    version="2.0.0",
    docs_url="/v1/docs",
    redoc_url="/v1/redoc",
    openapi_url="/v1/openapi.json",
)

app.include_router(router)

# Mangum handler for AWS Lambda
handler = Mangum(app)
