-- drop table if exists demo.bronze.raw_customer_profile;
-- drop table if exists demo.bronze.raw_order_transactions;

drop table if exists demo.silver.dim_customers;
drop table if exists demo.silver.fct_orders;
drop table if exists demo.silver.fct_orders_extended;

drop table if exists demo.golden.agg_customer_monthly_stats;
drop table if exists demo.diamond.sem_customer_transaction_summary;
drop table if exists demo.diamond.sem_regional_monthly_aov;