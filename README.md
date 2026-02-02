# 📊 SaaS Subscription Analytics

A comprehensive web application for SaaS business analytics, providing real-time insights into subscription metrics. Computes key metrics like MRR, ARR, Renewal Rate, LTV, Retention, and more from Stripe data synced periodically into a Clickhouse database.

## Features

- **Real-time Analytics Dashboard**: Interactive visualizations of subscription metrics
- **Key Metrics Tracking**:
  - Monthly Recurring Revenue (MRR)
  - Annual Recurring Revenue (ARR)
  - Customer Lifetime Value (LTV)
  - Customer Retention Rate
  - Renewal Rate
  - Churn Rate
  - Total Customer Count
- **Stripe Integration**: Automated data sync from Stripe
- **High-Performance Database**: Clickhouse for fast analytics queries
- **Modern Tech Stack**: React frontend with FastAPI backend

## Architecture

```
┌─────────────┐         ┌──────────────┐         ┌────────────┐
│   Stripe    │────────▶│   FastAPI    │────────▶│ Clickhouse │
│     API     │  Sync   │   Backend    │  Query  │  Database  │
└─────────────┘         └──────────────┘         └────────────┘
                               │
                               │ REST API
                               │
                        ┌──────▼──────┐
                        │    React    │
                        │  Frontend   │
                        └─────────────┘
```

## Tech Stack

### Backend
- **FastAPI**: Modern Python web framework for building APIs
- **Clickhouse**: High-performance columnar database for analytics
- **Stripe SDK**: Integration with Stripe payment platform
- **Pydantic**: Data validation and settings management

### Frontend
- **React**: UI library for building interactive interfaces
- **Vite**: Fast build tool and development server
- **Recharts**: Charting library for data visualization
- **Axios**: HTTP client for API requests

## Prerequisites

- Python 3.11+
- Node.js 20+
- Docker and Docker Compose (for containerized deployment)
- Stripe account with API key

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/ondraz/subscriptions.git
cd subscriptions
```

### 2. Set up environment variables

```bash
cp .env.example .env
# Edit .env and add your Stripe API key
```

### 3. Option A: Docker Deployment (Recommended)

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

The application will be available at:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Documentation: http://localhost:8000/docs

### 3. Option B: Local Development

#### Backend Setup

```bash
cd backend
pip install -r requirements.txt

# Start Clickhouse (using Docker)
docker run -d --name clickhouse \
  -p 8123:8123 -p 9000:9000 \
  clickhouse/clickhouse-server

# Run database initialization
docker exec -i clickhouse clickhouse-client < ../init-db.sql

# Start backend server
python -m uvicorn main:app --reload
```

#### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

## Usage

### 1. Sync Stripe Data

Before viewing metrics, sync data from Stripe:

```bash
curl -X POST http://localhost:8000/api/sync/stripe
```

Or use the API documentation interface at http://localhost:8000/docs

### 2. View Dashboard

Open http://localhost:3000 in your browser to view the analytics dashboard.

### 3. API Endpoints

#### Get Metrics Summary
```bash
curl http://localhost:8000/api/metrics/summary
```

#### Get Specific Metric
```bash
curl "http://localhost:8000/api/metrics/mrr?interval=month"
```

Available metrics:
- `mrr` - Monthly Recurring Revenue
- `arr` - Annual Recurring Revenue
- `ltv` - Customer Lifetime Value
- `retention` - Customer Retention Rate
- `renewal_rate` - Subscription Renewal Rate
- `churn_rate` - Customer Churn Rate
- `customer_count` - Total Customer Count

#### Get Customers
```bash
curl "http://localhost:8000/api/customers?limit=100"
```

## Project Structure

```
subscriptions/
├── backend/
│   ├── __init__.py
│   ├── main.py              # FastAPI application entry point
│   ├── models.py            # Data models (Pydantic)
│   ├── database.py          # Clickhouse client
│   ├── analytics.py         # Metrics computation engine
│   ├── stripe_sync.py       # Stripe data synchronization
│   ├── requirements.txt     # Python dependencies
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/      # React components
│   │   │   ├── Dashboard.jsx
│   │   │   ├── MetricsSummary.jsx
│   │   │   └── MetricChart.jsx
│   │   ├── services/        # API client
│   │   │   └── api.js
│   │   ├── App.jsx
│   │   ├── App.css
│   │   ├── main.jsx
│   │   └── index.css
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── Dockerfile
├── docker-compose.yml       # Docker orchestration
├── init-db.sql             # Database schema
├── .env.example            # Environment variables template
└── README.md

```

## Metrics Explanation

### Monthly Recurring Revenue (MRR)
Total predictable revenue generated each month from active subscriptions. Annual plans are normalized to monthly values.

### Annual Recurring Revenue (ARR)
Annualized version of MRR (MRR × 12). Represents the yearly run rate.

### Customer Lifetime Value (LTV)
Average revenue per customer divided by churn rate. Indicates total value of a customer relationship.

### Retention Rate
Percentage of customers who remain active over a period. Calculated as: ((Customers at End - New Customers) / Customers at Start) × 100

### Renewal Rate
Percentage of subscriptions that renew when they reach their period end. Higher is better.

### Churn Rate
Percentage of customers who cancel or don't renew. Lower is better.

## Development

### Running Tests

```bash
# Backend tests
cd backend
pytest

# Frontend tests
cd frontend
npm test
```

### Code Formatting

```bash
# Backend
cd backend
black .
ruff check .

# Frontend
cd frontend
npm run lint
```

## Configuration

### Clickhouse Configuration

Edit `init-db.sql` to customize database schema and indexes.

### Stripe Webhook (Optional)

For real-time updates, configure a Stripe webhook:

1. Go to Stripe Dashboard → Developers → Webhooks
2. Add endpoint: `https://your-domain.com/api/webhook/stripe`
3. Select events: `customer.subscription.created`, `customer.subscription.updated`, etc.
4. Add webhook handling endpoint in `backend/main.py`

## Deployment

### Production Deployment

1. Update environment variables for production
2. Use production-grade database credentials
3. Enable HTTPS
4. Set up reverse proxy (nginx/Caddy)
5. Configure monitoring and logging

```bash
# Build production images
docker-compose -f docker-compose.prod.yml build

# Deploy
docker-compose -f docker-compose.prod.yml up -d
```

## Troubleshooting

### Database Connection Issues

```bash
# Check Clickhouse is running
docker ps | grep clickhouse

# Test connection
docker exec clickhouse clickhouse-client --query "SELECT 1"
```

### Frontend Not Loading

```bash
# Check backend is running
curl http://localhost:8000/

# Check CORS settings in backend/main.py
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Stripe for payment processing and subscription management
- Clickhouse for high-performance analytics
- FastAPI for the excellent Python web framework
- React and Recharts for the frontend experience
