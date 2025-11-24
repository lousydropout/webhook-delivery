# Phase 4: Monitoring Deprecated Endpoint Usage

## Overview

This guide explains how to monitor usage of deprecated endpoints using AWS CloudWatch metrics. This helps track migration progress and plan endpoint removal.

## Deprecated Endpoints

The following endpoints are deprecated and should be monitored:

1. **POST /v1/events/{event_id}/retry** - Replaced by `PATCH /v1/events/{event_id}`
2. **PATCH /v1/tenants/current** - Replaced by `PATCH /v1/tenants/{tenant_id}`

## CloudWatch Metrics

API Gateway automatically publishes metrics for all endpoints. Key metrics to monitor:

- **Count** - Number of requests
- **4XXError** - Client errors (including 400, 403, 404)
- **5XXError** - Server errors
- **Latency** - Request latency

## Monitoring Commands

### 1. Get API Gateway ID

First, identify your API Gateway REST API ID:

```bash
# Get API Gateway ID from CloudFormation stack
aws cloudformation describe-stacks \
  --stack-name WebhookDeliveryStack \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiGatewayRestApiId`].OutputValue' \
  --output text

# Or list all APIs
aws apigateway get-rest-apis \
  --query 'items[?name==`Webhook Delivery API`].id' \
  --output text
```

### 2. Monitor Deprecated Retry Endpoint

```bash
# Set variables
API_ID="your-api-gateway-id"
METRIC_NAME="Count"
RESOURCE="/v1/events/{event_id}/retry"
METHOD="POST"

# Get request count for last 24 hours
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApiGateway \
  --metric-name $METRIC_NAME \
  --dimensions Name=ApiName,Value="Webhook Delivery API" \
               Name=Resource,Value=$RESOURCE \
               Name=Method,Value=$METHOD \
  --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 \
  --statistics Sum \
  --output json | jq '.Datapoints | map(.Sum) | add // 0'
```

### 3. Monitor Deprecated Tenant Current Endpoint

```bash
RESOURCE="/v1/tenants/current"
METHOD="PATCH"

aws cloudwatch get-metric-statistics \
  --namespace AWS/ApiGateway \
  --metric-name Count \
  --dimensions Name=ApiName,Value="Webhook Delivery API" \
               Name=Resource,Value=$RESOURCE \
               Name=Method,Value=$METHOD \
  --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 \
  --statistics Sum \
  --output json | jq '.Datapoints | map(.Sum) | add // 0'
```

### 4. Compare Deprecated vs RESTful Endpoints

```bash
# Count for deprecated retry endpoint
DEPRECATED_RETRY=$(aws cloudwatch get-metric-statistics \
  --namespace AWS/ApiGateway \
  --metric-name Count \
  --dimensions Name=ApiName,Value="Webhook Delivery API" \
               Name=Resource,Value="/v1/events/{event_id}/retry" \
               Name=Method,Value="POST" \
  --start-time $(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 86400 \
  --statistics Sum \
  --output json | jq '[.Datapoints[].Sum] | add // 0')

# Count for RESTful update endpoint
RESTFUL_UPDATE=$(aws cloudwatch get-metric-statistics \
  --namespace AWS/ApiGateway \
  --metric-name Count \
  --dimensions Name=ApiName,Value="Webhook Delivery API" \
               Name=Resource,Value="/v1/events/{event_id}" \
               Name=Method,Value="PATCH" \
  --start-time $(date -u -d '7 days ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 86400 \
  --statistics Sum \
  --output json | jq '[.Datapoints[].Sum] | add // 0')

echo "Deprecated Retry Endpoint: $DEPRECATED_RETRY requests"
echo "RESTful Update Endpoint: $RESTFUL_UPDATE requests"
echo "Migration Progress: $(echo "scale=2; $RESTFUL_UPDATE / ($DEPRECATED_RETRY + $RESTFUL_UPDATE) * 100" | bc)%"
```

## CloudWatch Dashboard

### Create Custom Dashboard

1. Go to CloudWatch Console → Dashboards
2. Create new dashboard: "Deprecated Endpoints Monitoring"
3. Add widgets for:
   - Deprecated endpoint request counts
   - RESTful endpoint request counts
   - Error rates
   - Migration progress percentage

### Dashboard JSON (Example)

```json
{
  "widgets": [
    {
      "type": "metric",
      "properties": {
        "metrics": [
          ["AWS/ApiGateway", "Count", {"stat": "Sum", "label": "Deprecated Retry"}],
          [".", ".", {"stat": "Sum", "label": "RESTful Update"}]
        ],
        "period": 3600,
        "stat": "Sum",
        "region": "us-east-1",
        "title": "Endpoint Usage Comparison"
      }
    }
  ]
}
```

## Log-Based Monitoring

### Filter CloudWatch Logs

API Gateway logs can also be filtered to track deprecated endpoint usage:

```bash
# Get log group name
LOG_GROUP="/aws/apigateway/WebhookDeliveryStack-TriggerApi"

# Count deprecated retry endpoint calls in last hour
aws logs filter-log-events \
  --log-group-name $LOG_GROUP \
  --filter-pattern '{ $.requestPath = "/v1/events/*/retry" && $.httpMethod = "POST" }' \
  --start-time $(($(date +%s) - 3600))000 \
  --query 'events | length(@)'
```

## Automated Monitoring Script

See `scripts/monitor_deprecated_endpoints.sh` for an automated script that:
- Queries CloudWatch metrics for deprecated endpoints
- Compares with RESTful alternatives
- Calculates migration progress
- Generates a report

## Migration Progress Tracking

### Key Metrics

1. **Usage Trend**: Are deprecated endpoints still being used?
2. **Migration Rate**: How quickly are users migrating to RESTful endpoints?
3. **Error Rate**: Are deprecated endpoints causing issues?
4. **Zero Usage Period**: How long since last usage?

### Decision Criteria for Removal

After 90-day deprecation period, consider removal if:
- ✅ Zero usage for 30+ consecutive days
- ✅ RESTful alternatives have >95% adoption
- ✅ No critical errors from deprecated endpoints
- ✅ Migration guide has been available for 90+ days

## Alerting

### CloudWatch Alarms

Set up alarms for:
- Deprecated endpoint usage spikes (may indicate new integration)
- High error rates on deprecated endpoints
- Zero usage threshold (ready for removal)

Example alarm:

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "DeprecatedEndpointStillInUse" \
  --alarm-description "Alert if deprecated endpoints receive requests" \
  --metric-name Count \
  --namespace AWS/ApiGateway \
  --statistic Sum \
  --period 86400 \
  --evaluation-periods 1 \
  --threshold 0 \
  --comparison-operator GreaterThanThreshold \
  --dimensions Name=Resource,Value="/v1/events/{event_id}/retry" \
               Name=Method,Value="POST"
```

## Reporting

### Weekly Migration Report

Generate weekly reports showing:
- Deprecated endpoint usage (count, trend)
- RESTful endpoint adoption rate
- Migration progress percentage
- Recommendations for next steps

Run the monitoring script weekly and track results over time.

## Next Steps

1. Set up CloudWatch dashboard for visual monitoring
2. Configure alerts for usage patterns
3. Generate baseline metrics (current usage)
4. Track migration progress weekly
5. Plan removal date based on usage trends

---

**Note**: API Gateway metrics may take a few minutes to appear. Use CloudWatch Logs for real-time monitoring.

