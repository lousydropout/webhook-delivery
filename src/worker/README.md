# Mock Worker

Simulates Zapier's trigger engine by polling for events and processing them.

## Usage

### Single Tenant
```bash
export API_URL="https://your-api-gateway-url"
export API_KEY="tenant_acme_live_xxx"
export TENANT_NAME="acme"
python src/worker/mock_worker.py
```

### Multiple Tenants
```bash
export API_URL="https://your-api-gateway-url"
export API_KEYS="key1,key2,key3"
export TENANT_NAMES="acme,globex,initech"
python src/worker/mock_worker.py
```

## Environment Variables

- `API_URL` (required): API Gateway endpoint URL
- `API_KEY`: Single tenant API key
- `API_KEYS`: Comma-separated list of API keys for multi-tenant mode
- `TENANT_NAMES`: Comma-separated list of tenant names (for logging)
- `POLL_INTERVAL`: Seconds between polls (default: 5)
