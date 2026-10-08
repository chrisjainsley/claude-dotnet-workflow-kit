"""Parse and validate the review's ```flowmap block: the layer map of a change.

The block is plain lines, so a review can be written and diffed by hand:

    lanes: API, Application, Domain, Infrastructure
    rows: Orders, Billing

    node endpoint: CancelOrderMutation
      lane: API
      row: Orders
      file: src/Orders.Api/GraphQL/CancelOrderMutation.cs
      kind: api
      note: mutation cancelOrder

    test endpoint-tests: CancelOrderMutationTests
      covers: endpoint
      file: tests/Orders.Api.Tests/GraphQL/CancelOrderMutationTests.cs

    endpoint -> handler
    repo ~> consumer: OrderCancelled via outbox
    before: mutation-old -> repo: saves, then publishes

`lanes` are slice names from the profile, in display order; `rows` group nodes (one per
service, or per journey) and default to a single unnamed row. A `node` sits in one lane
and row; a `test` sits in the Tests strip under the lane of the node it `covers`.
`status` (new, modified, deleted, context, missing) defaults to the file's git status at
render time; `view` (before, after, both) defaults from the status: new nodes exist only
after, deleted nodes only before. `->` is a call, `~>` an event or message; an edge shows
in a view when both of its nodes do, and a `before:` or `after:` prefix limits it further.

Examples attach to a node from a fence in the Changes section whose caption starts with
`@<node id>`: ```graphql @endpoint Query. A ```record fence holds one data row, one
`column | value | note` line per field.
"""
import re

STATUSES = ("new", "modified", "deleted", "context", "missing")
VIEWS = ("before", "after", "both")
NODE_KEYS = ("lane", "row", "file", "status", "kind", "note", "covers", "view")
TESTS_LANE = "Tests"
MAX_NODES = 16
ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
HEAD_RE = re.compile(r"^(node|test)\s+([^:\s]+)\s*:\s*(.+)$")
EDGE_RE = re.compile(r"^(?:(before|after)\s*:\s*)?([^\s:]+)\s*(->|~>)\s*([^\s:]+)\s*(?::\s*(.+))?$")
KEY_RE = re.compile(r"^\s+([a-z]+)\s*:\s*(.*)$")
EXAMPLE_RE = re.compile(r"^@([^\s]+)\s*(.*)$")


def split_list(value):
    return [part.strip() for part in value.split(",") if part.strip()]


def parse(text):
    """Return (spec, errors). spec = {lanes, rows, nodes: [dict], edges: [dict]}."""
    spec = {"lanes": [], "rows": [], "nodes": [], "edges": []}
    errors, node = [], None
    for n, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        key = KEY_RE.match(raw)
        if key and node is not None:
            name, value = key.group(1), key.group(2).strip()
            if name not in NODE_KEYS:
                errors.append(f"line {n}: unknown node key '{name}' (use {', '.join(NODE_KEYS)})")
            else:
                node[name] = value
            continue
        line = raw.strip()
        node = None
        if line.startswith(("lanes:", "rows:")):
            name, value = line.split(":", 1)
            spec[name] = split_list(value)
            continue
        head = HEAD_RE.match(line)
        if head:
            node = {"id": head.group(2), "title": head.group(3).strip(), "test": head.group(1) == "test"}
            if node["test"]:
                node["lane"] = TESTS_LANE
            spec["nodes"].append(node)
            continue
        edge = EDGE_RE.match(line)
        if edge:
            spec["edges"].append({"only": edge.group(1) or "", "from": edge.group(2), "to": edge.group(4),
                                  "event": edge.group(3) == "~>", "label": (edge.group(5) or "").strip()})
            continue
        errors.append(f"line {n}: not a lanes, rows, node, test or edge line: '{line[:60]}'")
    return spec, errors


def validate(spec, slices=None):
    """Structural errors in a parsed spec; slices are the profile's allowed lane names."""
    errors = []
    lanes, rows = spec["lanes"], spec["rows"]
    if not lanes:
        errors.append("needs a 'lanes:' line naming the slices in display order")
    allowed = set(slices or []) - {TESTS_LANE}
    for lane in lanes:
        if lane == TESTS_LANE:
            errors.append("Tests is not a lane: write test nodes, which sit in the Tests strip")
        elif slices and lane not in allowed:
            errors.append(f"lane '{lane}' is not a slice in this profile ({', '.join(sorted(allowed))})")
    ids = {}
    for node in spec["nodes"]:
        nid = node["id"]
        if not ID_RE.match(nid):
            errors.append(f"node id '{nid}': use lower case letters, digits, - or _")
        if nid in ids:
            errors.append(f"node id '{nid}' is used twice")
        ids[nid] = node
    plain = [n for n in spec["nodes"] if not n["test"]]
    if not plain:
        errors.append("needs at least one node")
    if len(plain) > MAX_NODES:
        errors.append(f"{len(plain)} nodes, cap {MAX_NODES}: show the path, not every file")
    for node in spec["nodes"]:
        nid = node["id"]
        if not node["test"] and node.get("lane") not in lanes:
            errors.append(f"node '{nid}': lane '{node.get('lane', '')}' is not in the lanes line")
        if node.get("row") and node["row"] not in rows:
            errors.append(f"node '{nid}': row '{node['row']}' is not in the rows line")
        if node.get("status") and node["status"] not in STATUSES:
            errors.append(f"node '{nid}': status must be one of {', '.join(STATUSES)}")
        if node.get("view") and node["view"] not in VIEWS:
            errors.append(f"node '{nid}': view must be one of {', '.join(VIEWS)}")
        if node.get("file") and not re.fullmatch(r"`?[^`\s]+`?", node["file"]):
            errors.append(f"node '{nid}': file must be one repo-relative path")
        if node["test"]:
            covers = node.get("covers", "")
            if not covers:
                errors.append(f"test '{nid}': needs 'covers: <node id>'")
            elif covers not in ids or ids[covers]["test"]:
                errors.append(f"test '{nid}': covers unknown node '{covers}'")
            if node.get("status") != "missing" and not node.get("file"):
                errors.append(f"test '{nid}': needs a file, or status: missing")
        elif node.get("status") not in ("context", "missing") and not node.get("file"):
            errors.append(f"node '{nid}': needs a file (or status: context)")
    for edge in spec["edges"]:
        for end in ("from", "to"):
            target = ids.get(edge[end])
            if target is None:
                errors.append(f"edge {edge['from']} -> {edge['to']}: unknown node '{edge[end]}'")
            elif target["test"]:
                errors.append(f"edge {edge['from']} -> {edge['to']}: tests take 'covers', not edges")
    return errors


def example_target(caption):
    """The node id an example fence's caption attaches it to, or None."""
    m = EXAMPLE_RE.match(caption.strip())
    return (m.group(1), m.group(2).strip()) if m else None


def record_rows(body):
    """[(column, value, note)] from a ```record fence."""
    rows = []
    for line in body.splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("|")]
        rows.append((parts[0], parts[1] if len(parts) > 1 else "", parts[2] if len(parts) > 2 else ""))
    return rows


def validate_examples(examples, spec):
    """examples: [(lang, caption, body)] whose caption starts with @."""
    ids = {n["id"] for n in spec["nodes"]}
    errors = []
    for lang, caption, body in examples:
        nid, label = example_target(caption)
        if nid not in ids:
            errors.append(f"example '@{nid}' names no node in the flowmap")
        if not label:
            errors.append(f"example '@{nid}': add a caption after the id, e.g. '@{nid} Query'")
        if lang == "record" and any(len(r) < 2 or not r[1] for r in record_rows(body)):
            errors.append(f"example '@{nid} {label}': record lines are 'column | value | note'")
    return errors


def resolve(spec, file_status):
    """Fill each node's status and views. file_status(path) -> 'A'|'M'|'D'|None."""
    for node in spec["nodes"]:
        status = node.get("status")
        if not status:
            git = file_status(node["file"].strip("`")) if node.get("file") else None
            status = {"A": "new", "D": "deleted", "M": "modified"}.get(git or "", "context")
            if node["test"] and not node.get("file"):
                status = "missing"
        node["status"] = status
        view = node.get("view") or {"new": "after", "deleted": "before"}.get(status, "both")
        node["views"] = ["before", "after"] if view == "both" else [view]
    return spec
