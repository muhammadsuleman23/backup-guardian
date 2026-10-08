#!/usr/bin/env python3
"""Backup Guardian: file changes detect karta hai, versioned backups banata hai,
purana version restore karta hai, aur fail hone par alert deta hai."""

import argparse
import hashlib
import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_SOURCE = Path.home() / "guardian-test" / "source"
DEFAULT_DEST = Path.home() / "guardian-test" / "backups"


# ---------- Chhote helper functions ----------

def sha256_of(path):
    """File ka SHA-256 hash (fingerprint). Bari file ho to tukron mein parhte hain."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_index(dest):
    """index.json (pichli run ka register) parho. Pehli baar ho to khali register."""
    path = dest / "index.json"
    if not path.exists():
        return {"files": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_index(dest, index):
    """Pehle temporary file mein likho, phir badal do. Beech mein crash ho to
    purana index kharab nahi hota."""
    tmp = dest / "index.json.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
    tmp.replace(dest / "index.json")


def setup_logging(dest):
    dest.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(dest / "guardian.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def alert(message):
    """Alert: log mein ERROR likho aur desktop notification bhejo (agar ho sake)."""
    logging.error("ALERT: %s", message)
    if shutil.which("notify-send"):
        try:
            subprocess.run(
                ["notify-send", "-u", "critical", "Backup Guardian", message],
                timeout=5, check=False,
            )
        except Exception:
            pass  # notification na chale to bhi backup ka kaam na ruke


# ---------- Commands ----------

def cmd_backup(args):
    source, dest = args.source.expanduser(), args.dest.expanduser()
    setup_logging(dest)

    if not source.is_dir():
        alert(f"Source folder nahi mila: {source}")
        return 1

    index = load_index(dest)
    seen, new, modified, unchanged, failed = set(), [], [], 0, []
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    for path in sorted(source.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue  # symlink aur folders skip
        rel = path.relative_to(source).as_posix()
        seen.add(rel)

        try:
            st = path.stat()
            entry = index["files"].get(rel)

            # Sasti jaanch: size aur time wohi hain to hash ki zaroorat nahi
            if entry and entry["size"] == st.st_size and entry["mtime"] == st.st_mtime:
                unchanged += 1
                continue

            digest = sha256_of(path)
            if entry and entry["versions"][-1]["hash"] == digest:
                # Sirf time badla, content wohi hai
                entry["size"], entry["mtime"] = st.st_size, st.st_mtime
                unchanged += 1
                continue

            # Naya ya badla hua: versioned copy banao
            number = len(entry["versions"]) + 1 if entry else 1
            stored = f"versions/{rel}/v{number}_{stamp}"
            target = dest / stored
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            if sha256_of(target) != digest:
                raise RuntimeError("copy ka hash match nahi hua")

            version = {"version": number, "time": stamp, "hash": digest, "stored": stored}
            if entry:
                entry["versions"].append(version)
                modified.append(rel)
            else:
                entry = {"versions": [version]}
                new.append(rel)
            entry["size"], entry["mtime"] = st.st_size, st.st_mtime
            index["files"][rel] = entry
            logging.info("Backed up: %s (v%d)", rel, number)

        except Exception as e:
            failed.append(rel)
            logging.error("Fail: %s (%s)", rel, e)

    deleted = [rel for rel in index["files"] if rel not in seen]
    save_index(dest, index)

    logging.info(
        "Summary: new=%d modified=%d unchanged=%d deleted_from_source=%d failed=%d",
        len(new), len(modified), unchanged, len(deleted), len(failed),
    )
    for rel in deleted:
        logging.warning("Source se gayab (purane versions safe hain): %s", rel)

    if failed:
        alert(f"{len(failed)} file(s) ka backup fail hua. Detail: {dest / 'guardian.log'}")
        return 1
    return 0


def cmd_status(args):
    source, dest = args.source.expanduser(), args.dest.expanduser()
    if not source.is_dir():
        print(f"Source folder nahi mila: {source}")
        return 1
    index = load_index(dest)
    new, changed = [], []
    for path in sorted(source.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(source).as_posix()
        entry = index["files"].get(rel)
        if entry is None:
            new.append(rel)
        elif sha256_of(path) != entry["versions"][-1]["hash"]:
            changed.append(rel)
    if not new and not changed:
        print("Sab kuch backup ho chuka hai. Koi tabdeeli nahi.")
        return 0
    for rel in new:
        print(f"NEW       {rel}")
    for rel in changed:
        print(f"MODIFIED  {rel}")
    print("Backup ke liye chalao: python3 guardian.py backup")
    return 0


def cmd_versions(args):
    index = load_index(args.dest.expanduser())
    if not index["files"]:
        print("Abhi koi backup nahi hai.")
        return 0
    if args.file is None:
        for rel, entry in sorted(index["files"].items()):
            print(f"{rel}  ({len(entry['versions'])} version)")
        return 0
    entry = index["files"].get(args.file)
    if entry is None:
        print(f"Index mein ye file nahi mili: {args.file}")
        return 1
    for v in entry["versions"]:
        print(f"v{v['version']}  {v['time']}  {v['hash'][:12]}")
    return 0


def cmd_restore(args):
    source, dest = args.source.expanduser(), args.dest.expanduser()
    index = load_index(dest)
    entry = index["files"].get(args.file)
    if entry is None:
        print(f"Index mein ye file nahi mili: {args.file}")
        return 1

    number = args.version or entry["versions"][-1]["version"]
    match = [v for v in entry["versions"] if v["version"] == number]
    if not match:
        print(f"Version v{number} maujood nahi. Dekhne ke liye: versions {args.file}")
        return 1
    version = match[0]

    # Default: alag restored/ folder mein. Asli file tab hi overwrite jab --overwrite do.
    if args.overwrite:
        out = source / args.file
    else:
        out = dest / "restored" / f"v{number}_{args.file}"
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dest / version["stored"], out)

    if sha256_of(out) != version["hash"]:
        print("Warning: restore ki hui file ka hash match nahi hua!")
        return 1
    print(f"Restore ho gaya (hash verified): {out}")
    return 0


# ---------- Command line ----------

def main():
    parser = argparse.ArgumentParser(description="Backup Guardian")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                        help="wo folder jis ka backup lena hai")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST,
                        help="backups kahan rakhne hain")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("backup", help="tabdeel hui files ka versioned backup lo")
    sub.add_parser("status", help="dekho kya badla hai (backup nahi leta)")

    p = sub.add_parser("versions", help="files ya kisi file ke versions dikhao")
    p.add_argument("file", nargs="?")

    p = sub.add_parser("restore", help="kisi file ka purana version wapas lao")
    p.add_argument("file")
    p.add_argument("--version", type=int, help="konsa version (default: sab se naya)")
    p.add_argument("--overwrite", action="store_true",
                   help="asli file ki jagah par wapas rakho")

    args = parser.parse_args()
    commands = {"backup": cmd_backup, "status": cmd_status,
                "versions": cmd_versions, "restore": cmd_restore}
    sys.exit(commands[args.command](args))


if __name__ == "__main__":
    main()
