from fastapi import FastAPI
from mangum import Mangum
from routes import router

app = FastAPI(
    title="Webhook Delivery API",
    description="Multi-tenant webhook delivery system",
    version="2.0.0"
)

app.include_router(router)

# Mangum handler for AWS Lambda
handler = Mangum(app)
