# CLAUDE.md

Start from @readme.md and the documentation index in @agents.md, and follow the project rules in @doc/development.md.

Before changing the pipeline, read "Data flow" and "Validation rules" in `doc/pipeline.md`, and update them in the same change as whatever they describe. Before changing stores, events or volumes, read `doc/dataset.md` and update it in the same change. A new architecture decision gets an entry in `doc/decisions.md`.

**Tests:** run `python -m unittest discover -s tests` before handing over a change, and add a test for every new feature or data rule. See `doc/testing.md`.

**Mandatory: never commit or push.** Leave all changes uncommitted for the owner to review in VS Code's Source Control view. End every task with a list of the files you added, changed or deleted, as links. The owner commits and pushes. See "Working rules → Agents" in `doc/development.md`.
