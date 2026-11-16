"""Create the Genie agent from its versioned definition, or update it in place. Run by the job deploy_kpi_genie.

The definition (src/kpi_genie.json) holds the title, the description and the serialized space: data sources,
instructions, example SQL, filters, joins and benchmarks. An agent with the same title in the parent folder is
updated, so redeploying never makes a copy. Uses the Genie REST API through the Databricks SDK's API client,
which every serverless environment provides. See doc/kpi_genie.md.
"""
import argparse
import json

API = "/api/2.0/genie/spaces"


def find_space(client, title, parent_path):
    """The id of the agent with this title in this folder, or None."""
    token = None
    while True:
        page = client.do("GET", API, query={"page_token": token} if token else None) or {}
        for space in page.get("spaces", []):
            if space.get("title") == title and (space.get("parent_path") in (None, parent_path)):
                return space["space_id"]
        token = page.get("next_page_token")
        if not token:
            return None


def deploy(client, workspace, agent, warehouse_id, parent_path):
    """Create or update the agent; returns (action, space id)."""
    body = {
        "title": agent["title"],
        "description": agent["description"],
        "warehouse_id": warehouse_id,
        "serialized_space": json.dumps(agent["serialized_space"]),
    }
    space_id = find_space(client, agent["title"], parent_path)
    if space_id:
        client.do("PATCH", f"{API}/{space_id}", body=body)
        return "updated", space_id
    workspace.mkdirs(parent_path)  # create-space fails if the folder doesn't exist
    created = client.do("POST", API, body={**body, "parent_path": parent_path})
    return "created", created["space_id"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--definition", required=True, help="Path of kpi_genie.json in the workspace")
    parser.add_argument("--warehouse-id", required=True)
    parser.add_argument("--parent-path", required=True)
    args = parser.parse_args()

    from databricks.sdk import WorkspaceClient  # available on serverless; imported here so tests need no SDK

    with open(args.definition, encoding="utf-8") as f:
        agent = json.load(f)
    w = WorkspaceClient()
    action, space_id = deploy(w.api_client, w.workspace, agent, args.warehouse_id, args.parent_path)
    print(f"Genie agent {action}: {agent['title']} ({space_id})")
    print(f"Open it at {w.config.host}/genie/rooms/{space_id}")


if __name__ == "__main__":
    main()
