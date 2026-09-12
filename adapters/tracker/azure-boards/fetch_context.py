#!/usr/bin/env python
"""Gather the Context section's raw material for a work item.

Usage: python fetch_context.py <work-item-id> --out plans/<slug>/context

Writes <out>/context.md (a stub for the plan's "## Context" section: parent feature,
sibling stories, design links) and downloads design images next to it: image
attachments on the item, its parent and siblings, plus Figma frames when the
FIGMA_TOKEN environment variable holds a Figma personal access token. Without the
token, Figma links are listed for the reader to open and any PNG exported by hand
into the same folder is picked up by the builder as long as it is referenced.

Needs an authenticated Azure CLI (az boards / az rest). Read-only against Azure
DevOps and Figma; writes only under --out.
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ORG = os.environ.get("AZURE_DEVOPS_ORG", "")  # falls back to az devops configure defaults
PROJECT = os.environ.get("AZURE_DEVOPS_PROJECT", "")  # falls back to the profile's tracker_project
ADO_RESOURCE = "499b84ac-1321-427f-aa17-267ca6975798"
FIGMA_RE = re.compile(r"https://(?:www\.)?figma\.com/(?:file|design|proto|board)/([A-Za-z0-9]+)/[^\s\"'<>\\)]*")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
TEXT_FIELDS = ("System.Description", "Microsoft.VSTS.Common.AcceptanceCriteria", "Microsoft.VSTS.TCM.ReproSteps")


def az(args, binary_out=None):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    cmd = "az " + args
    if binary_out:
        cmd += f' --output-file "{binary_out}"'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:400])
    return result.stdout


def show(item_id):
    return json.loads(az(f"boards work-item show --id {item_id} --org {ORG} --output json"))


def batch(ids):
    if not ids:
        return []
    body = json.dumps({"ids": ids, "fields": ["System.Title", "System.State", "System.WorkItemType"]}).replace('"', '\\"')
    out = az(
        f'rest --method post --url "{ORG}/{PROJECT.replace(" ", "%20")}/_apis/wit/workitemsbatch?api-version=7.1" '
        f'--resource {ADO_RESOURCE} --headers "Content-Type=application/json" --body "{body}" --output json'
    )
    return json.loads(out).get("value", [])


def strip_html(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def first_sentences(text, limit=45):
    words = strip_html(text).split()
    return " ".join(words[:limit]) + ("..." if len(words) > limit else "")


def item_url(item_id):
    return f"{ORG}/{PROJECT.replace(' ', '%20')}/_workitems/edit/{item_id}"


def text_blob(item):
    fields = item.get("fields", {})
    parts = [str(fields.get(f, "")) for f in TEXT_FIELDS]
    for rel in item.get("relations", []) or []:
        if rel.get("rel") == "Hyperlink":
            parts.append(rel.get("url", ""))
    return "\n".join(parts)


def figma_links(item):
    links = []
    for match in FIGMA_RE.finditer(text_blob(item)):
        url = html.unescape(match.group(0)).rstrip(".,;")
        node = re.search(r"node-id=([0-9A-Za-z%:-]+)", url)
        node_id = node.group(1).replace("-", ":").replace("%3A", ":") if node else None
        links.append({"url": url, "file_key": match.group(1), "node_id": node_id, "source": item["id"]})
    return links


def attachment_images(item):
    found = []
    for rel in item.get("relations", []) or []:
        name = (rel.get("attributes") or {}).get("name", "")
        if rel.get("rel") == "AttachedFile" and name.lower().endswith(IMAGE_EXT):
            found.append({"url": rel["url"], "name": name, "source": item["id"]})
    for match in re.finditer(r'<img[^>]+src="([^"]+_apis/wit/attachments/[^"]+)"', text_blob(item)):
        url = html.unescape(match.group(1))
        found.append({"url": url, "name": f"inline-{len(found) + 1}.png", "source": item["id"]})
    return found


def download_attachment(att, out_dir, index):
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", att["name"])
    target = out_dir / f"attachment-{index}-{safe}"
    az(f'rest --method get --url "{att["url"]}" --resource {ADO_RESOURCE}', binary_out=str(target))
    return target


def figma_frames(links, out_dir, token):
    frames = []
    for n, link in enumerate(links, start=1):
        entry = dict(link, file=None, name=None)
        if token and link["node_id"]:
            try:
                req = urllib.request.Request(
                    f"https://api.figma.com/v1/images/{link['file_key']}?ids={link['node_id']}&format=png&scale=1",
                    headers={"X-Figma-Token": token})
                images = json.loads(urllib.request.urlopen(req, timeout=60).read()).get("images", {})
                image_url = next(iter(images.values()), None)
                if image_url:
                    target = out_dir / f"figma-{n}.png"
                    urllib.request.urlretrieve(image_url, target)
                    entry["file"] = target
                names_req = urllib.request.Request(
                    f"https://api.figma.com/v1/files/{link['file_key']}/nodes?ids={link['node_id']}&depth=1",
                    headers={"X-Figma-Token": token})
                nodes = json.loads(urllib.request.urlopen(names_req, timeout=60).read()).get("nodes", {})
                entry["name"] = next((v["document"]["name"] for v in nodes.values() if v and v.get("document")), None)
            except Exception as error:  # noqa: BLE001 - report and keep the link
                entry["error"] = str(error)[:200]
        frames.append(entry)
    return frames


def resolve_org_project(org, project):
    """Org: flag, AZURE_DEVOPS_ORG, then az devops configure defaults. Project: flag, env, profile, az defaults."""
    global ORG, PROJECT
    defaults = {}
    try:
        for line in az("devops configure --list").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                defaults[key.strip()] = value.strip()
    except (RuntimeError, OSError):
        pass
    ORG = (org or ORG or defaults.get("organization", "")).rstrip("/")
    if not project and not PROJECT:
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
        from kit_profile import resolve_profile
        project = resolve_profile().get("tracker_project", "")
    PROJECT = project or PROJECT or defaults.get("project", "")
    if not ORG or not PROJECT:
        sys.exit("fetch_context: set --org/--project, AZURE_DEVOPS_ORG/AZURE_DEVOPS_PROJECT, the profile's tracker_project, or az devops configure --defaults")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("item_id", type=int)
    ap.add_argument("--out", required=True)
    ap.add_argument("--org", help="Azure DevOps organization URL")
    ap.add_argument("--project", help="Azure DevOps project name")
    args = ap.parse_args()
    resolve_org_project(args.org, args.project)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    item = show(args.item_id)
    fields = item["fields"]
    parent_id = fields.get("System.Parent")
    parent = show(parent_id) if parent_id else None
    sibling_ids = []
    if parent:
        for rel in parent.get("relations", []) or []:
            if rel.get("rel") == "System.LinkTypes.Hierarchy-Forward":
                sid = int(rel["url"].rsplit("/", 1)[1])
                if sid != args.item_id:
                    sibling_ids.append(sid)
    siblings = batch(sibling_ids)

    sources = [item] + ([parent] if parent else [])
    links, attachments, seen = [], [], set()
    for src in sources:
        for link in figma_links(src):
            if link["url"] not in seen:
                seen.add(link["url"])
                links.append(link)
        attachments.extend(attachment_images(src))
    for sib in siblings:
        try:
            full = show(sib["id"])
        except RuntimeError:
            continue
        for link in figma_links(full):
            if link["url"] not in seen:
                seen.add(link["url"])
                links.append(link)
        attachments.extend(attachment_images(full))

    downloaded = []
    for n, att in enumerate(attachments, start=1):
        try:
            downloaded.append((att, download_attachment(att, out_dir, n)))
        except RuntimeError as error:
            print(f"attachment {att['name']} from AB#{att['source']} failed: {error}", file=sys.stderr)
    frames = figma_frames(links, out_dir, os.environ.get("FIGMA_TOKEN"))

    lines = ["## Context"]
    if parent:
        pf = parent["fields"]
        lines.append(
            f"**Parent feature:** [AB#{parent['id']} {pf.get('System.Title', '')}]({item_url(parent['id'])}) "
            f"({pf.get('System.WorkItemType', '')}, {pf.get('System.State', '')}). {first_sentences(pf.get('System.Description', ''))}"
        )
    else:
        lines.append("**Parent feature:** none linked.")
    if siblings:
        sib_text = "; ".join(
            f"[AB#{s['id']}]({item_url(s['id'])}) {s['fields'].get('System.Title', '')} ({s['fields'].get('System.State', '')})"
            for s in sorted(siblings, key=lambda s: s["id"])
        )
        lines.append(f"**Siblings in the feature:** {sib_text}.")
    lines.append("**Area:** <services, bounded context, key grains or aggregates; fill in from research>.")
    if frames or downloaded:
        lines.append("**Designs:**")
        for f in frames:
            label = f["name"] or f"Figma frame from AB#{f['source']}"
            lines.append(f"- [{label}]({f['url']})" + (" (no PNG: set FIGMA_TOKEN or export by hand)" if not f["file"] else ""))
        lines.append("")
        for f in frames:
            if f["file"]:
                lines.append(f"![{f['name'] or 'Figma frame'}]({out_dir.name}/{f['file'].name})")
        for att, path in downloaded:
            lines.append(f"![{att['name']} from AB#{att['source']}]({out_dir.name}/{path.name})")
    else:
        lines.append("**Designs:** none attached to the item, its parent or siblings.")
    stub = out_dir / "context.md"
    stub.write_text("\n\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {stub}: parent={'AB#' + str(parent_id) if parent_id else 'none'}, siblings={len(siblings)}, "
          f"figma links={len(links)} (png {sum(1 for f in frames if f['file'])}), attachments={len(downloaded)}")
    for f in frames:
        if f.get("error"):
            print(f"figma {f['url']}: {f['error']}", file=sys.stderr)


if __name__ == "__main__":
    main()
