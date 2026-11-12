"""Where the images of a game night live on disk: loose in its data folders, or zipped by the nightly archive job."""
import glob
import os
import shutil
import zipfile
from datetime import datetime

from core import config

ARCHIVE_NAME = "archive.zip"
COLLAGE_PREFIX = "collage_"


def story_prefix(event_id):
    """File-name prefix of the story images of one event (create_story_image); used to find them on deletion."""
    return f"story_{event_id}_"


def day_folder(date):
    return os.path.join(config.DATA_DIR, date.strftime("%Y"), date.strftime("%m"), date.strftime("%d"))


def candidate_folders(date, events):
    """The folders that can hold the night's images: the ones of the stored event image paths, then the day folder
    (left out when date is None)."""
    folders = []
    for ev in events:
        if not ev.get('image_path'):
            continue
        folder = os.path.dirname(ev['image_path'])
        folders.append(folder)
        parts = folder.split(os.sep)
        if not os.path.isabs(folder) and parts[0] == "data":  # stored relative to the repo; DATA_DIR may live elsewhere
            folders.append(os.path.join(config.DATA_DIR, *parts[1:]))
    if date is not None:
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


def restore_image_file(path):
    """Makes sure `path` exists as a loose file, extracting it from its folder's archive.zip if the nightly
    job zipped it. True when the file is there afterwards."""
    if not path:
        return False
    if os.path.isfile(path):
        return True
    folder = os.path.dirname(path)
    found = find_local_file(os.path.basename(path), [folder])
    if not found or found[1] is None:
        return False
    extract_member(found[0], found[1], folder)
    return os.path.isfile(path)


def remove_from_archive(zip_path, names):
    """Rewrites zip_path without the members whose base name is in `names` (the zip is deleted if nothing is left).

    Returns the base names actually removed.
    """
    names = set(names)
    if not names or not os.path.isfile(zip_path):
        return []
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        removed = [info for info in infos if os.path.basename(info.filename) in names]
        if not removed:
            return []
        kept = [info for info in infos if info not in removed]
        if kept:
            tmp_path = f"{zip_path}.tmp"
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as target:
                for info in kept:
                    target.writestr(info, archive.read(info))
    if kept:
        os.replace(tmp_path, zip_path)
    else:
        os.remove(zip_path)
    return [os.path.basename(info.filename) for info in removed]


def _event_date(event):
    try:
        return datetime.strptime((event.get('normalized_date') or '').strip(), "%d-%m-%Y")
    except ValueError:
        return None


def delete_event_images(event, keep_image=False):
    """Deletes the event image and the event's story images, loose or inside an archive.zip, from the folders that
    can hold them (the image's folder and the event day's folder). keep_image=True leaves `image_path` alone (another
    row still uses the file). Returns the base names deleted."""
    folders = candidate_folders(_event_date(event), [event])
    image_name = os.path.basename(event['image_path']) if event.get('image_path') and not keep_image else None
    prefix = story_prefix(event['id'])

    def wanted(name):
        return name == image_name or (name.startswith(prefix) and name.endswith(".jpg"))

    deleted = []
    for folder in folders:
        for path in glob.glob(os.path.join(folder, "*")):
            name = os.path.basename(path)
            if os.path.isfile(path) and wanted(name):
                os.remove(path)
                deleted.append(name)
        zip_path = os.path.join(folder, ARCHIVE_NAME)
        if os.path.isfile(zip_path):
            with zipfile.ZipFile(zip_path) as archive:
                members = {os.path.basename(info.filename) for info in archive.infolist()}
            deleted += remove_from_archive(zip_path, [name for name in members if wanted(name)])
    return deleted
