-- ============================================================
-- 15 - Create the current-simulation views
-- Targets: workspace.test02_streaming.current_simulation
--          workspace.test02_streaming.current_people_counter_events
--          workspace.test02_streaming.current_sales_transactions
--
-- Every START of the people-stream app begins a new simulation with a
-- new, sortable simulation_id (its UTC start time), and the pipeline
-- keeps running: silver holds every simulation. These views keep only
-- the latest one, so readers (the sales dashboard) follow a new
-- simulation within seconds, with no full refresh.
--
-- Plain views: evaluated at query time, so they add no delay to silver.
-- Run after the pipeline has created the silver tables with their
-- simulation_id column. Idempotent. Rules: doc/warehouse.md, section 6.
-- ============================================================

-- The current simulation: the latest simulation_id among the people
-- events. People events always arrive before the first sale, so both
-- views below switch to a new simulation at the same moment.
CREATE OR REPLACE VIEW workspace.test02_streaming.current_simulation
COMMENT 'The current simulation: the latest simulation_id in silver_people_counter_events'
AS
SELECT MAX(simulation_id) AS simulation_id
FROM workspace.test02_streaming.silver_people_counter_events;

CREATE OR REPLACE VIEW workspace.test02_streaming.current_people_counter_events
COMMENT 'Silver people-counter events of the current simulation only'
AS
SELECT e.*
FROM workspace.test02_streaming.silver_people_counter_events e
WHERE e.simulation_id = (SELECT simulation_id FROM workspace.test02_streaming.current_simulation);

CREATE OR REPLACE VIEW workspace.test02_streaming.current_sales_transactions
COMMENT 'Silver sales transactions of the current simulation only'
AS
SELECT s.*
FROM workspace.test02_streaming.silver_sales_transactions s
WHERE s.simulation_id = (SELECT simulation_id FROM workspace.test02_streaming.current_simulation);
