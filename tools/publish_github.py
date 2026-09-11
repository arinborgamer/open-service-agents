"""Publish only this reviewed repository using the owner's existing Git credential helper.

Credentials stay in memory and are never printed or written. This script is an
operator action, not a tool available to the runtime agents.
"""
import argparse
import json
import os
import subprocess
import tomllib
import urllib.request
import urllib.error
from pathlib import Path

OWNER = "arinborgamer"
REPO = "open-service-agents"


def authenticated():
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    result = subprocess.run(["git", "credential", "fill"], input=f"protocol=https\nhost=github.com\nusername={OWNER}\n\n", text=True, capture_output=True, env=env, check=True)
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    token = fields.get("password")
    if not token:
        raise RuntimeError("GitHub login is required.")
    def api(path, data=None, method=None):
        request = urllib.request.Request("https://api.github.com" + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "open-service-agents-publisher"}, method=method)
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    user = api("/user")
    if user["login"].lower() != OWNER:
        raise RuntimeError("Authenticated account does not match the requested repository owner.")
    return api, user


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("check", "create", "release", "status"))
    args = parser.parse_args()
    api, user = authenticated()
    if args.action == "check":
        print(json.dumps({"login": user["login"], "id": user["id"], "authenticated": True}))
    elif args.action == "create":
        try:
            existing = api(f"/repos/{OWNER}/{REPO}")
            print(json.dumps({"url": existing["html_url"], "existing": True, "private": existing["private"]}))
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            result = api("/user/repos", {"name": REPO, "description": "Open-source digital-product, creator-partnership and fulfillment agents. Local AI, durable automation, Razorpay. No Whop.",
                        "private": False, "has_issues": True, "has_wiki": False, "has_projects": False, "auto_init": False})
            print(json.dumps({"url": result["html_url"], "created": True}))
    elif args.action == "release":
        version = tomllib.loads((Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text())['project']['version']
        changelog = (Path(__file__).resolve().parents[1] / 'CHANGELOG.md').read_text(encoding='utf-8')
        notes = changelog.split('## ' + version + '\n', 1)[1].split('\n## ', 1)[0].strip()
        result = api(f"/repos/{OWNER}/{REPO}/releases", {"tag_name": "v" + version, "target_commitish": "main", "name": "v" + version + " - engineering preview", "prerelease": True,
            "body": notes + "\n\nEngineering preview, not a turnkey income system. No earnings claimed. See README.md and docs/VALIDATION.md for setup and verification limits."})
        print(json.dumps({"release": result["html_url"]}))
    elif args.action == "status":
        result = api(f"/repos/{OWNER}/{REPO}/actions/runs?per_page=5")
        print(json.dumps([{"id": r["id"], "status": r["status"], "conclusion": r["conclusion"], "url": r["html_url"], "sha": r["head_sha"]} for r in result["workflow_runs"]]))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never print exception bodies which could contain provider responses.
        print(json.dumps({"error": type(exc).__name__, "status": getattr(exc, "code", None)}))
        raise SystemExit(1)
