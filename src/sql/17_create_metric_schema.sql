-- ============================================================
-- 17 - Create the metric schema
-- Target: workspace.test02_metric
--
-- Holds the metric views and KPIs only: governed business measures
-- computed live from the silver tables and the dimensions. Nothing
-- else writes here. Idempotent.
-- Rules: doc/kpi_metrics.md.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS workspace.test02_metric
COMMENT 'Metric views and KPIs: business measures over silver and the dimensions (doc/kpi_metrics.md)';
