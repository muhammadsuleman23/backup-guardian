# Backup Guardian

A small command-line tool for Linux that watches a folder, keeps **versioned backups** of every file that changes, lets you **restore** an older version, and **alerts you when a backup fails**. Built with Python's standard library only (no extra packages to install).

## Features
- **Change detection:** compares file size and modified time first (fast), then confirms with a SHA-256 hash, so only real content changes create a new version
- **Versioned backups:** every changed file is saved as `v1`, `v2`, ... and old versions are never overwritten
- **Restore:** bring back any version; the restored copy is hash-verified
- **Failure alerts:** errors are written to a log file, the program exits with code 1, and a desktop notification is sent when `notify-send` is available
- **Per-file error handling:** one unreadable file does not stop the backup of the other files
- **Safe index writes:** the index is written to a temporary file first, so a crash cannot corrupt it

## How it works
```
source folder -> scan files -> size/mtime changed? -> SHA-256 hash
              -> compare with index.json -> new or changed? -> save versioned copy
              -> update index.json -> write log, alert on failure
```

`index.json` is the register of the last run: for each file it stores the size, modified time, and the list of versions with their hashes.

## Usage
By default the tool backs up `~/guardian-test/source` into `~/guardian-test/backups`. Use `--source` and `--dest` to change this.

```bash
python3 guardian.py status                      # show what changed (does not back up)
python3 guardian.py backup                      # back up new and changed files
python3 guardian.py versions                    # list backed-up files
python3 guardian.py versions notes.txt          # list versions of one file
python3 guardian.py restore notes.txt --version 1   # restore v1 to backups/restored/
python3 guardian.py restore notes.txt --overwrite   # put the latest version back in the source folder

python3 guardian.py --source ~/Documents --dest /mnt/backup-disk/docs backup
```

By default, `restore` never overwrites your original file. It writes the old version to a separate `restored/` folder. You must pass `--overwrite` to replace the original.

## Run it automatically with cron
```bash
crontab -e
```
Add (runs every hour; change the path to match your home folder):
```
0 * * * * /usr/bin/python3 /home/YOUR-USER/backup-guardian/guardian.py backup >> /home/YOUR-USER/guardian-test/cron.log 2>&1
```
The log file and the exit code are the reliable alerts. Desktop notifications are a bonus and may not appear when the job runs from cron.

## Limitations
- Backups are stored wherever `--dest` points. If that is the same disk as the source, a disk failure loses both, so point `--dest` to a different disk or drive
- Each changed file is copied in full (no compression or deduplication)
- Symlinks are skipped
- Backups are not encrypted

## Tech Stack
Python 3 (tested on 3.14): `argparse`, `hashlib`, `json`, `logging`, `pathlib`, `shutil`, `subprocess`

## Future Improvements
- Email alerts
- Retention policy (keep only the last N versions)
- Compression and deduplication
- Simple web page to browse versions

## Author
Muhammad Suleman
