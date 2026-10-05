"""Download the private capture corpus from the Hugging Face bucket named in .corpus.json.

Fetches the main corpus package (public-research-v1) and the Pro annotation manifest,
verifies every shard and extracted file against the package manifest's SHA-256, and
unpacks only what the labeling tool reads into runs/corpus/:

  public-research-v1/captures/<site>/<page>/state-N/   capture, environment, DOM, geometry,
                                                       compact view and its source map
  public-research-v1/labels/<id>-passN/result.json     Gemini Flash silver outlines
  public-research-v1/export-manifest.json              hashes for everything above
  pro-pages.json                                       pages that also have a Pro outline

Requires the `hf` CLI, logged in (`hf auth login`). Shards are deleted after a
successful unpack. Nothing here is committed: runs/ is gitignored.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".corpus.json"
OUT = ROOT / "runs/corpus"
SNAPSHOT = "snapshots/2026-09-14"
PACKAGE = "public-research-v1"
WANTED = re.compile(
    r"captures/[0-9a-f]+/[0-9a-f]+/state-\d+/"
    r"(capture\.json|environment\.json|document\.html|geometry\.json"
    r"|compression/document-00000\.html|compression/document-00000\.source-map\.json)"
    r"|labels/[0-9a-f]+-pass\d+/result\.json")
PAGE = re.compile(r"captures/([0-9a-f]{24})/([0-9a-f]{24})/")


def safe(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(p in {"", ".", ".."} for p in value.split("/")):
        raise ValueError(f"unsafe path in manifest: {value!r}")
    return path


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def hf_cp(remote, local):
    local.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["hf", "buckets", "cp", remote, str(local)], check=True, stdout=subprocess.DEVNULL)


def unpack(manifest, shard_dir, destination):
    """Verify shards, then write wanted members to their logical paths. Returns files written."""
    by_physical = {a["path"]: a for a in manifest["artifacts"] if WANTED.fullmatch(a["logical_path"])}
    written = 0
    for shard in manifest["shards"]:
        archive = shard_dir / safe(shard["path"])
        if sha256(archive) != shard["sha256"]:
            raise ValueError(f"{shard['path']}: shard checksum mismatch")
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar:
                record = by_physical.get(member.name)
                if record is None:
                    continue
                if not member.isfile() or record["shard"] != shard["path"]:
                    raise ValueError(f"{member.name}: unexpected tar member")
                data = tar.extractfile(member).read()
                if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                    raise ValueError(f"{member.name}: file checksum mismatch")
                target = destination / safe(record["logical_path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                written += 1
    if written != len(by_physical):
        raise ValueError(f"expected {len(by_physical)} files, found {written}")
    return written


def verify(destination):
    """Re-hash every unpacked file against the saved manifest. Returns files checked."""
    manifest = json.loads((destination / "export-manifest.json").read_text())
    wanted = [a for a in manifest["artifacts"] if WANTED.fullmatch(a["logical_path"])]
    for record in wanted:
        if sha256(destination / safe(record["logical_path"])) != record["sha256"]:
            raise ValueError(f"{record['logical_path']}: checksum mismatch")
    return len(wanted)


def pro_pages(manifest):
    return sorted({"/".join(m.groups()) for f in manifest["files"] if (m := PAGE.search(f["path"]))})


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUT)
    parser.add_argument("--verify", action="store_true", help="re-check an existing download, no network")
    args = parser.parse_args()
    if args.verify:
        print(f"OK: {verify(args.output / PACKAGE)} files match the manifest.")
        return
    if not CONFIG.exists():
        sys.exit("Missing .corpus.json; copy .corpus.example.json and set the bucket.")
    if not shutil.which("hf"):
        sys.exit("The hf CLI is required: uv tool install huggingface_hub, then hf auth login.")
    bucket = json.loads(CONFIG.read_text())["bucket"].rstrip("/")
    destination = args.output / PACKAGE
    if destination.exists():
        sys.exit(f"{destination} already exists; delete it to fetch again.")

    staging = args.output / f".{PACKAGE}.download"
    remote = f"{bucket}/{SNAPSHOT}/vm/{PACKAGE}"
    hf_cp(f"{remote}/export-manifest.json", staging / "export-manifest.json")
    manifest = json.loads((staging / "export-manifest.json").read_text())
    for shard in manifest["shards"]:
        local = staging / safe(shard["path"])
        if local.exists() and sha256(local) == shard["sha256"]:
            continue  # resumed run
        print(f"Downloading {shard['path']} ({shard['bytes'] / 1e6:.0f} MB)")
        hf_cp(f"{remote}/{shard['path']}", local)

    partial = args.output / f".{PACKAGE}.partial"
    shutil.rmtree(partial, ignore_errors=True)
    written = unpack(manifest, staging, partial)
    shutil.copyfile(staging / "export-manifest.json", partial / "export-manifest.json")
    partial.rename(destination)
    shutil.rmtree(staging)

    hf_cp(f"{bucket}/{SNAPSHOT}/pro-annotations/manifest.json", args.output / ".pro-manifest.json")
    pages = pro_pages(json.loads((args.output / ".pro-manifest.json").read_text()))
    (args.output / "pro-pages.json").write_text(json.dumps(pages, indent=1))
    (args.output / ".pro-manifest.json").unlink()
    print(f"Unpacked {written} files into {destination}; {len(pages)} Pro pages listed.")


if __name__ == "__main__":
    main()
