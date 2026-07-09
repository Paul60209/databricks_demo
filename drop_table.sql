-- drop table if exists demo.bronze.raw_customer_profile;
-- drop table if exists demo.bronze.raw_order_transactions;

drop table if exists demo.silver.dim_customers;
drop table if exists demo.silver.fct_orders;
drop table if exists demo.silver.fct_orders_extended;

drop table if exists demo.golden.agg_customer_monthly_stats;

-- Diamond layer is now a Unity Catalog Metric View, not a table — use DROP VIEW.
-- Re-create it afterward via: python metric_views/deploy_metric_view.py
drop view if exists demo.diamond.vw_customer_orders_metrics;

-- One-time cleanup: these two physical tables are orphaned now that Diamond
-- was migrated to the Metric View above. DLT no longer manages them (removing
-- a table from the pipeline definition doesn't auto-drop the underlying data),
-- so they must be dropped manually. Safe to delete these two lines once
-- confirmed dropped in the workspace.
drop table if exists demo.diamond.sem_customer_transaction_summary;
drop table if exists demo.diamond.sem_regional_monthly_aov;