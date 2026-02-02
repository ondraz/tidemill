-- Initialize Clickhouse database schema for subscription analytics

-- Create database
CREATE DATABASE IF NOT EXISTS subscriptions;

USE subscriptions;

-- Customers table
CREATE TABLE IF NOT EXISTS customers (
    id String,
    email String,
    name String,
    created_at DateTime,
    description String,
    updated_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY id;

-- Subscriptions table
CREATE TABLE IF NOT EXISTS subscriptions (
    id String,
    customer_id String,
    status String,
    current_period_start DateTime,
    current_period_end DateTime,
    created_at DateTime,
    canceled_at Nullable(DateTime),
    ended_at Nullable(DateTime),
    plan_id String,
    plan_amount Float64,
    plan_currency String,
    plan_interval String,
    updated_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (id, customer_id);

-- Invoices table
CREATE TABLE IF NOT EXISTS invoices (
    id String,
    customer_id String,
    subscription_id String,
    amount_paid Float64,
    currency String,
    created_at DateTime,
    status String,
    period_start DateTime,
    period_end DateTime,
    updated_at DateTime DEFAULT now()
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (id, customer_id);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status) TYPE minmax GRANULARITY 4;
CREATE INDEX IF NOT EXISTS idx_subscriptions_customer ON subscriptions(customer_id) TYPE minmax GRANULARITY 4;
CREATE INDEX IF NOT EXISTS idx_invoices_customer ON invoices(customer_id) TYPE minmax GRANULARITY 4;
