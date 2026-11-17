"""How to switch the whole solution on and off by hand in Databricks, and the app's signature. Standard library only.

The app's "Switch on / off" tab shows these steps; doc/people_stream.md, "Switch on and off", lists the same steps
and a test checks that the two agree. Change the steps here and in the doc together.
"""

AUTHOR = "Michele Piunti"
MADE_IN = "November 2026"
REPO_URL = "https://github.com/MPiunti/nov26_stream"
SIGNATURE = f"This app is made by {AUTHOR} in {MADE_IN}."

JOB = "[dev michele_piunti] retail-simulator"
SIMULATOR_APP = "people-stream-michele-piunti"
DASHBOARD_APP = "sales-bi-michele-piunti"

# (step, where, action, why)
SWITCH_ON = (
    ("0", "Workspace → Git folder retail_people_counter_bundle", "Pull",
     "Only after new commits on main: brings the Git folder up to date. Deployed apps keep running their "
     "deployed version"),
    ("1", f"Jobs & Pipelines → {JOB}", "Resume",
     "First, because the pipeline needs about a minute to start: it's ready when the first events arrive"),
    ("2", f"Compute → Apps → {SIMULATOR_APP}", "Start, and wait for Running",
     "This app: the simulation engine"),
    ("3", f"Compute → Apps → {DASHBOARD_APP}", "Start",
     "The BI engine; it can start at the same time as step 2"),
    ("4", "This app, above the tabs", "Check the cockpit switches, then press START",
     "Begins a new simulation: 8 minutes (48 simulated hours), or until STOP"),
    ("5", "The sales dashboard app", "Nothing to do",
     "It switches to the new simulation within seconds; its footer shows the simulation id"),
)

SWITCH_OFF = (
    ("1", "This app", "Press STOP, or let the run finish", "No more events or sales are written"),
    ("2", f"Jobs & Pipelines → {JOB}", "Pause", "The pipeline stops: no serverless compute running or billed"),
    ("3", f"Compute → Apps → {SIMULATOR_APP} and {DASHBOARD_APP}", "Stop", "The apps' compute stops"),
    ("4", "SQL warehouse (Serverless Starter Warehouse)", "Nothing to do",
     "It stops by itself after a while without queries"),
)

NOTES = (
    "The SQL warehouse needs no step: it starts when an app first queries it.",
    "The Genie agent (Retail KPI Assistant) needs no step: it queries the SQL warehouse only when someone asks it a question.",
    "Don't re-run src/sql/15_create_current_simulation_views.sql: re-creating the views drops the sales "
    "dashboard's permission to read them.",
    "Pull the Git folder before deploying from it: deploying an older commit rolls an app back to that commit's "
    "permissions too (e.g. the sales dashboard loses its access to the Genie agent).",
    "Deploy app bundles from the PC (bundle deploy, then bundle run). A deploy from the Git folder's "
    "Deployments panel uploads no files: Compute > Apps > Deploy then restarts the app on the files of the "
    "last PC deploy, an older version.",
)
