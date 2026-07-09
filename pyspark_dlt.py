import dlt
from pyspark.sql.functions import col, expr, row_number, lower, coalesce, to_date, date_trunc, count, sum
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
# The Diamond layer (semantic layer) is no longer managed by this DLT
# pipeline. It's a Unity Catalog Metric View, deployed independently via
# metric_views/deploy_metric_view.py — see CLAUDE.md for details.
# =====================================================================