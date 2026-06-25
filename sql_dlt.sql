-- =====================================================================
-- 3. SILVER LAYER: dim_customers (Dimension Table)
-- Business Logic: Standardize country names using CASE WHEN, and deduplicate using window functions.
-- Note: Dimension deduplication requires a full scan, hence declared as a LIVE TABLE (Materialized View).
-- =====================================================================
CREATE OR REFRESH LIVE TABLE dim_customers
COMMENT "Customer dimension table after country name standardization and latest record deduplication"
AS
WITH ranked_customers AS (
  SELECT 
    customer_id,
    customer_name,
    -- Column Cleaning: Ensure basic email format validity, default to 'Unknown' if invalid
    CASE 
      WHEN lower(email) NOT LIKE '%@%' OR email IS NULL THEN 'Unknown'
      ELSE email 
    END AS email,
    -- Column Standardization: Align messy country names into standard formats
    CASE 
      WHEN lower(country) IN ('taiwan', 'tw') THEN 'Taiwan'
      WHEN lower(country) IN ('japan', 'jp') THEN 'Japan'
      WHEN lower(country) IN ('united states', 'us', 'usa') THEN 'United States'
      ELSE 'Unknown'
    END AS country,
    created_ts,
    -- Partition by customer_id and rank by created_ts descending to capture the latest profile
    ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY created_ts DESC) as rn
  FROM demo.bronze.raw_customer_profile
)
SELECT customer_id, customer_name, email, country, created_ts
FROM ranked_customers
WHERE rn = 1;


-- =====================================================================
-- 4. SILVER LAYER: fct_orders (Fact Table)
-- Business Logic: Use CONSTRAINT to intercept dirty data (amount <= 0), and standardize mixed date formats into DATE type.
-- Note: External data source must use the STREAM() keyword to enable incremental computation.
-- =====================================================================
CREATE OR REFRESH STREAMING TABLE fct_orders(
  -- Data Quality Control: Drop the row completely if the amount is invalid
  CONSTRAINT valid_amount EXPECT (amount > 0) ON VIOLATION DROP ROW
)
COMMENT "Order fact table after filtering abnormal amounts and standardizing date formats"
AS SELECT
  order_id,
  customer_id,
  amount,
  status,
  -- Core Transformation: Unify 'yyyy-MM-dd', 'yyyy/MM/dd', and 'yyyyMMdd' formats into DATE
  COALESCE(
    to_date(order_dt, 'yyyy-MM-dd'),
    to_date(order_dt, 'yyyy/MM/dd'),
    to_date(order_dt, 'yyyyMMdd')
  ) AS order_date
FROM STREAM(demo.bronze.raw_order_transactions);


-- =====================================================================
-- 5. SILVER LAYER: fct_orders_extended (Fact-Dimension Extended Wide Table)
-- Business Logic: LEFT JOIN the streaming fact table with the deduplicated static dimension table.
-- Note: This demonstrates a classic Stream-Static Join architecture.
-- =====================================================================
CREATE OR REFRESH STREAMING TABLE fct_orders_extended
COMMENT "Streaming wide table integrating order facts and customer dimensions"
AS SELECT
  o.order_id,
  o.customer_id,
  o.amount,
  o.status,
  o.order_date,
  c.customer_name,
  c.email,
  c.country
-- Querying internal streaming tables requires the live. prefix
FROM STREAM(live.fct_orders) o
LEFT JOIN live.dim_customers c
  ON o.customer_id = c.customer_id;


-- =====================================================================
-- 6. GOLD LAYER: agg_customer_monthly_stats (Business Aggregation Layer)
-- Business Logic: Group by Year-Month, Country, and Customer from the wide table to calculate operational metrics.
-- Note: Data aggregations require a holistic view, hence declared as a LIVE TABLE for full materialization.
-- =====================================================================
CREATE OR REFRESH LIVE TABLE agg_customer_monthly_stats
COMMENT "Monthly operational metrics aggregated by year-month, country, and customer"
AS SELECT
  date_trunc('MONTH', order_date) AS order_month,
  country,
  customer_id,
  customer_name,
  COUNT(order_id) AS total_order_count,
  SUM(amount) AS total_order_amount
FROM live.fct_orders_extended
GROUP BY 1, 2, 3, 4;


-- =====================================================================
-- 7. DIAMOND LAYER: sem_customer_transaction_summary (Semantic: Customer Transactions)
-- Business Logic: Expose customer-level monthly transaction stats as a clean semantic surface.
-- Supports filtering by customer_id, customer_name, or order_month in the query layer.
-- Note: Reads from gold aggregation; declared as LIVE TABLE for full materialization.
-- =====================================================================
CREATE OR REFRESH LIVE TABLE sem_customer_transaction_summary
COMMENT "Semantic table exposing per-customer monthly transaction count and revenue for downstream query and AI agent consumption"
AS SELECT
  customer_id,
  customer_name,
  country,
  order_month,
  total_order_count,
  total_order_amount,
  ROUND(total_order_amount / total_order_count, 2) AS avg_order_value
FROM live.agg_customer_monthly_stats;


-- =====================================================================
-- 8. DIAMOND LAYER: sem_regional_monthly_aov (Semantic: Regional AOV)
-- Business Logic: Aggregate to country + month level and compute AOV (Average Order Value).
-- Supports filtering by country or order_month in the query layer.
-- Note: Reads from gold aggregation; declared as LIVE TABLE for full materialization.
-- =====================================================================
CREATE OR REFRESH LIVE TABLE sem_regional_monthly_aov
COMMENT "Semantic table exposing regional monthly AOV (Average Order Value) for downstream query and AI agent consumption"
AS SELECT
  country,
  order_month,
  SUM(total_order_count)                                      AS total_order_count,
  ROUND(SUM(total_order_amount), 2)                           AS total_order_amount,
  ROUND(SUM(total_order_amount) / SUM(total_order_count), 2) AS aov
FROM live.agg_customer_monthly_stats
GROUP BY country, order_month;