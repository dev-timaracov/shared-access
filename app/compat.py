"""Deprecated Plane response aliases at the transport boundary, not in business logic."""


def legacy_response(result):
    if not isinstance(result, dict):
        return result
    result = dict(result)
    provider = result.get("tracker_provider")
    if provider == "plane":
        if "external_id" in result:
            result["plane_item_id"] = result["external_id"]
        if "tracker_workspace" in result:
            result["plane_workspace"] = result["tracker_workspace"]
            result["plane_project_id"] = result["tracker_project_id"]
        if "tracker_sync" in result:
            result["plane_sync"] = result["tracker_sync"]
    tracker = result.get("tracker")
    if tracker and tracker["provider"] == "plane":
        result["plane"] = {key: value for key, value in tracker.items() if key != "provider"}
        snapshot = dict(tracker["snapshot"])
        if snapshot:
            snapshot["state"] = snapshot.get("state_id")
            snapshot["assignees"] = snapshot.get("assignee_ids", [])
            snapshot["parent"] = snapshot.get("parent_id")
            if "description_source" in snapshot.get("metadata", {}):
                snapshot["description_source"] = snapshot["metadata"]["description_source"]
            snapshot["comments"] = [
                {
                    "id": c.get("id"),
                    "comment_stripped": c.get("text"),
                    "comment_html": c.get("html"),
                    "created_at": c.get("created_at"),
                    "actor": c.get("author"),
                }
                for c in snapshot.get("comments", [])
            ]
        result["plane"]["snapshot"] = snapshot
    return result
