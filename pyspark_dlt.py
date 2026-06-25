import dlt
from pyspark.sql.functions import col, expr, row_number, lower, coalesce, to_date, date_trunc, count, sum, round
from pyspark.sql.window import Window

# =====================================================================
# 3. SILVER LAYER: dim_customers (Dimension Table)
# =====================================================================
@dlt.table(
    name="demo.silver.dim_customers",
    comment="Customer dimension table after country name standardization and latest record deduplication"
)
def dim_customers():
    # Define window specification for deduplication logic
    window_spec = Window.partitionBy("customer_id").orderBy(col("created_ts").desc())
    
    return (
        # Read from the external Bronze table registered in Unity Catalog
        spark.read.table("demo.bronze.raw_customer_profile")
        .withColumn("cleaned_email", 
                    expr("CASE WHEN lower(email) NOT LIKE '%@%' OR email IS NULL THEN 'Unknown' ELSE email END"))
        .withColumn("cleaned_country", 
                    expr("""CASE 
                            WHEN lower(country) IN ('taiwan', 'tw') THEN 'Taiwan'
                            WHEN lower(country) IN ('japan', 'jp') THEN 'Japan'
                            WHEN lower(country) IN ('united states', 'us', 'usa') THEN 'United States'
                            ELSE 'Unknown' END"""))
        .withColumn("rn", row_number().over(window_spec))
        .filter(col("rn") == 1)
        .select(
            col("customer_id"),
            col("customer_name"),
            col("cleaned_email").alias("email"),
            col("cleaned_country").alias("country"),
            col("created_ts")
        )
    )

# =====================================================================
# 4. SILVER LAYER: fct_orders (Fact Table)
# =====================================================================
@dlt.table(
    name="demo.silver.fct_orders",
    comment="Order fact table after filtering abnormal amounts and standardizing date formats"
)
# Define Data Quality Expectation: Drop the row if amount is less than or equal to 0
@dlt.expect_or_drop("valid_amount", "amount > 0")
def fct_orders():
    return (
        # Core: Use spark.readStream to consume the external transaction stream incrementally
        spark.readStream.table("demo.bronze.raw_order_transactions")
        .withColumn("order_date", coalesce(
            to_date(col("order_dt"), "yyyy-MM-dd"),
            to_date(col("order_dt"), "yyyy/MM/dd"),
            to_date(col("order_dt"), "yyyyMMdd")
        ))
        .select("order_id", "customer_id", "amount", "status", "order_date")
    )

# =====================================================================
# 5. SILVER LAYER: fct_orders_extended (Fact-Dimension Extended Wide Table)
# =====================================================================
@dlt.table(
    name="demo.silver.fct_orders_extended",
    comment="Streaming wide table integrating order facts and customer dimensions"
)
def fct_orders_extended():
    # Read from the internal streaming table
    orders_stream = dlt.readStream("fct_orders")
    # Read from the internal materialized view (static dataset)
    customers_df = dlt.read("dim_customers")
    
    # Execute Stream-Static Join
    return orders_stream.join(customers_df, "customer_id", "left")

# =====================================================================
# 6. GOLD LAYER: agg_customer_monthly_stats (Business Aggregation Layer)
# =====================================================================
@dlt.table(
    name="demo.golden.agg_customer_monthly_stats",
    comment="Monthly operational metrics aggregated by year-month, country, and customer"
)
def agg_customer_monthly_stats():
    return (
        # Read from the extended wide table for holistic full materialization
        dlt.read("fct_orders_extended")
        .groupBy(
            date_trunc("MONTH", col("order_date")).alias("order_month"),
            "country",
            "customer_id",
            "customer_name"
        )
        .agg(
            count("order_id").alias("total_order_count"),
            sum("amount").alias("total_order_amount")
        )
    )

# =====================================================================
# 7. DIAMOND LAYER: sem_customer_transaction_summary (Semantic: Customer Transactions)
# Business Logic: Expose customer-level monthly transaction stats as a clean semantic surface.
# Supports filtering by customer_id, customer_name, or order_month in the query layer.
# =====================================================================
@dlt.table(
    name="demo.diamond.sem_customer_transaction_summary",
    comment="Semantic table exposing per-customer monthly transaction count and revenue for downstream query and AI agent consumption"
)
def sem_customer_transaction_summary():
    gold = dlt.read("agg_customer_monthly_stats")
    return gold.select(
        col("customer_id"),
        col("customer_name"),
        col("country"),
        col("order_month"),
        col("total_order_count"),
        col("total_order_amount"),
        round(col("total_order_amount") / col("total_order_count"), 2).alias("avg_order_value")
    )

# =====================================================================
# 8. DIAMOND LAYER: sem_regional_monthly_aov (Semantic: Regional AOV)
# Business Logic: Aggregate to country + month level and compute AOV (Average Order Value).
# Supports filtering by country or order_month in the query layer.
# =====================================================================
@dlt.table(
    name="demo.diamond.sem_regional_monthly_aov",
    comment="Semantic table exposing regional monthly AOV (Average Order Value) for downstream query and AI agent consumption"
)
def sem_regional_monthly_aov():
    gold = dlt.read("agg_customer_monthly_stats")
    return (
        gold
        .groupBy("country", "order_month")
        .agg(
            sum("total_order_count").alias("total_order_count"),
            round(sum("total_order_amount"), 2).alias("total_order_amount"),
            round(sum("total_order_amount") / sum("total_order_count"), 2).alias("aov")
        )
    )