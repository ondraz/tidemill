"""
FastAPI backend for SaaS subscription analytics.
Provides REST API endpoints for querying subscription metrics from Clickhouse.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
from typing import List, Optional
import uvicorn

from models import MetricData, MetricType
from analytics import AnalyticsEngine
from database import ClickhouseClient

app = FastAPI(
    title="Subscription Analytics API",
    description="REST API for SaaS subscription business metrics",
    version="1.0.0"
)

# Configure CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database and analytics engine
db_client = ClickhouseClient()
analytics_engine = AnalyticsEngine(db_client)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "healthy", "service": "subscription-analytics"}


@app.get("/api/metrics/summary")
async def get_metrics_summary():
    """
    Get current summary of all key metrics.
    
    Returns:
        Dictionary with current values for all metrics
    """
    try:
        summary = await analytics_engine.get_summary()
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching summary: {str(e)}")


@app.get("/api/metrics/{metric_type}")
async def get_metric(
    metric_type: MetricType,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    interval: str = "month"
) -> List[MetricData]:
    """
    Get time-series data for a specific metric.
    
    Args:
        metric_type: Type of metric (mrr, arr, renewal_rate, ltv, retention)
        start_date: Start date in YYYY-MM-DD format (defaults to 1 year ago)
        end_date: End date in YYYY-MM-DD format (defaults to today)
        interval: Data aggregation interval (day, week, month, year)
    
    Returns:
        List of metric data points with date and value
    """
    try:
        # Parse dates or use defaults
        if not end_date:
            end = datetime.now()
        else:
            end = datetime.strptime(end_date, "%Y-%m-%d")
        
        if not start_date:
            start = end - timedelta(days=365)
        else:
            start = datetime.strptime(start_date, "%Y-%m-%d")
        
        # Get metric data from analytics engine
        data = await analytics_engine.get_metric(
            metric_type=metric_type,
            start_date=start,
            end_date=end,
            interval=interval
        )
        
        return data
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching metric: {str(e)}")


@app.post("/api/sync/stripe")
async def sync_stripe_data():
    """
    Trigger manual sync of Stripe data to Clickhouse.
    
    Returns:
        Sync status and statistics
    """
    try:
        from stripe_sync import StripeSync
        
        sync_service = StripeSync(db_client)
        result = await sync_service.sync_all()
        
        return {
            "status": "success",
            "synced_at": datetime.now().isoformat(),
            "statistics": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error syncing Stripe data: {str(e)}")


@app.get("/api/customers")
async def get_customers(
    limit: int = 100,
    offset: int = 0
):
    """
    Get list of customers with their subscription status.
    
    Args:
        limit: Maximum number of customers to return
        offset: Pagination offset
    
    Returns:
        List of customer records
    """
    try:
        customers = await db_client.get_customers(limit=limit, offset=offset)
        return customers
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching customers: {str(e)}")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
