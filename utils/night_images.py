"""Where the images of a game night live on disk: loose in its data folders, or zipped by the nightly archive job."""
import glob
import os
import shutil
import zipfile
from datetime import datetime

from core import config

ARCHIVE_NAME = "archive.zip"
COLLAGE_PREFIX = "collage_"


def day_folder(date):
    return os.path.join(config.DATA_DIR, date.strftime("%Y"), date.strftime("%m"), date.strftime("%d"))


def candidate_folders(date, events):
    """The folders that can hold the night's images: the ones of the stored event image paths, then the day folder."""
    folders = []
    for ev in events:
        if not ev.get('image_path'):
            continue
        folder = os.path.dirname(ev['image_path'])
        folders.append(folder)
        parts = folder.split(os.sep)
        if not os.path.isabs(folder) and parts[0] == "data":  # stored relative to the repo; DATA_DIR may live elsewhere
            folders.append(os.path.join(config.DATA_DIR, *parts[1:]))
    folders.append(day_folder(date))
    return list(dict.fromkeys(folders))


def find_local_file(name, folders):
    """(path, None) for a loose file, (zip path, member) for one inside an archive.zip, or None. Loose files win."""
    for folder in folders:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path, None
    for folder in folders:
        zip_path = os.path.join(folder, ARCHIVE_NAME)
        if not os.path.isfile(zip_path):
            continue
        with zipfile.ZipFile(zip_path) as archive:
            members = [info for info in archive.infolist() if os.path.basename(info.filename) == name]
        if members:
            return zip_path, max(members, key=lambda info: info.date_time).filename
    return None


def extract_member(zip_path, member, target_dir):
    path = os.path.join(target_dir, os.path.basename(member))
    with zipfile.ZipFile(zip_path) as archive, archive.open(member) as source, open(path, "wb") as target:
        shutil.copyfileobj(source, target)
    return path


def _collages(folders):
    """(timestamp, file name) of every collage, loose (modification time) or inside an archive.zip (member time)."""
    found = []
    for folder in folders:
        found += [(os.path.getmtime(path), os.path.basename(path))
                  for path in glob.glob(os.path.join(folder, f"{COLLAGE_PREFIX}*")) if os.path.isfile(path)]
        zip_path = os.path.join(folder, ARCHIVE_NAME)
        if os.path.isfile(zip_path):
            with zipfile.ZipFile(zip_path) as archive:
                found += [(datetime(*info.date_time).timestamp(), os.path.basename(info.filename))
                          for info in archive.infolist() if os.path.basename(info.filename).startswith(COLLAGE_PREFIX)]
    return found


def collage_names(folders):
    return list(dict.fromkeys(name for _stamp, name in _collages(folders)))


def newest_collage(folders):
    """The file name of the most recent collage (the one of the last recap run), or None. Ties go to the later name."""
    found = _collages(folders)
    return max(found)[1] if found else None
