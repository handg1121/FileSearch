"""Upload complete release assets to a draft, then optionally publish it atomically."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from updater import config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--body-file", type=Path, required=True)
    parser.add_argument("--target", required=True, help="Exact Git commit for this release")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    credentials = subprocess.run(["git", "-c", "credential.interactive=false", "credential", "fill"],
                                 input="protocol=https\nhost=github.com\n\n", text=True,
                                 capture_output=True, timeout=20, env=environment, check=True)
    fields = dict(line.split("=", 1) for line in credentials.stdout.splitlines() if "=" in line)
    token = fields["password"]
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
               "User-Agent": "FileSearch-release-tool", "X-GitHub-Api-Version": "2022-11-28"}

    def request(url, data=None, method=None, content_type="application/json"):
        req = urllib.request.Request(url, data=data, method=method,
                                     headers=dict(headers, **{"Content-Type": content_type}))
        with urllib.request.urlopen(req, timeout=180) as response:
            return json.load(response)

    base = f"https://api.github.com/repos/{config.REPOSITORY}"
    releases = request(base + "/releases?per_page=100")
    if any(r["tag_name"] == "v" + config.VERSION for r in releases):
        raise RuntimeError("This version already has a release; do not overwrite a published update")
    directory = ROOT / "dist/releases" / config.VERSION
    names = [f"FileSearch-{config.VERSION}-windows-x64.zip", f"FileSearch-update-{config.VERSION}-win64.zip", "update.json"]
    for name in names:
        if not (directory / name).is_file():
            raise RuntimeError("Missing release asset: " + name)
    release = request(base + "/releases", json.dumps({"tag_name": "v" + config.VERSION,
                      "target_commitish": args.target, "name": "FileSearch " + config.VERSION,
                      "body": args.body_file.read_text(encoding="utf-8"), "draft": True}).encode("utf-8"))
    upload = release["upload_url"].split("{")[0]
    for name in names:
        request(upload + "?" + urllib.parse.urlencode({"name": name}), (directory / name).read_bytes(),
                content_type="application/zip" if name.endswith(".zip") else "application/json")
    if args.publish:
        release = request(base + "/releases/" + str(release["id"]), b'{"draft":false}', method="PATCH")
    print(json.dumps({"url": release["html_url"], "draft": release["draft"]}))


if __name__ == "__main__":
    main()
