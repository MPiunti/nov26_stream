# agents.md

Entry point for AI agents working on this project. Start here, then read the pages that match your task.

## Documentation

| Topic | Page | Read it before |
|---|---|---|
| **Project rules** | [`readme.md`](readme.md) | Any change: layout, workspace, tools, pipeline data flow, validation rules, working rules, tests |
| **Dataset** | [`doc/dataset.md`](doc/dataset.md) | Touching stores, events or volumes: the store dimension and its distribution, macro regions, how people-counter events are streamed in, opening hours, the `N_AVG_PEOPLE_*` parameters |

Every page in `doc/` is listed in this table. Update a page in the same change as whatever it describes; describe each rule on one page only and link to it elsewhere.

## Mandatory rules

- **Tests:** run `python -m unittest discover -s tests` before handing over a change, and add a test for every new feature or data rule.
- **Never commit or push.** Leave all changes uncommitted for the owner to review. End every task with a list of the files you added, changed or deleted, as links.
- **Ask first** before deploying, running or full-refreshing the pipeline, or running SQL that writes data.

Details: "Working rules" and "Tests" in [`readme.md`](readme.md).
