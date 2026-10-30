import base64
import logging
from urllib.parse import quote

from core.astro.client import gh_request

logger = logging.getLogger(__name__)


def get_ref_sha(branch):
    response = gh_request("GET", f"git/ref/heads/{quote(branch, safe='/')}")
    if response.status_code != 200:
        logger.error(f"GitHub: Cannot read branch '{branch}': {response.status_code} - {response.text}")
        return None
    return response.json()["object"]["sha"]


def create_branch(name, from_branch):
    """Creates `name` from `from_branch`; an already existing branch is reused."""
    sha = get_ref_sha(from_branch)
    if not sha:
        return False
    response = gh_request("POST", "git/refs", json={"ref": f"refs/heads/{name}", "sha": sha})
    if response.status_code == 201:
        return True
    if response.status_code == 422 and "already exists" in response.text:
        logger.info(f"GitHub: Branch '{name}' already exists, reusing it.")
        return True
    logger.error(f"GitHub: Failed to create branch '{name}': {response.status_code} - {response.text}")
    return False


def get_file(path, branch):
    """The blob sha of `path` on `branch`, or None when the file does not exist."""
    response = gh_request("GET", f"contents/{quote(path)}", params={"ref": branch})
    if response.status_code == 200:
        return response.json().get("sha")
    return None


def get_file_text(path, branch):
    """The decoded text of `path` on `branch`, or None when it does not exist. Raises when GitHub is not configured."""
    response = gh_request("GET", f"contents/{quote(path)}", params={"ref": branch})
    if response.status_code != 200:
        return None
    return base64.b64decode(response.json().get("content", "")).decode("utf-8", "replace")


def put_file(path, content, message, branch):
    """Creates or updates `path` on `branch` with the text `content`."""
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": branch,
    }
    sha = get_file(path, branch)
    if sha:
        payload["sha"] = sha
    response = gh_request("PUT", f"contents/{quote(path)}", json=payload)
    if response.status_code not in (200, 201):
        logger.error(f"GitHub: Failed to commit '{path}' on '{branch}': {response.status_code} - {response.text}")
        return False
    return True


def merge_branch(head, base, message):
    """Merges `head` into `base`; 201 (merged) and 204 (nothing to merge) are both success."""
    response = gh_request("POST", "merges", json={"base": base, "head": head, "commit_message": message})
    if response.status_code in (201, 204):
        return True
    logger.error(f"GitHub: Failed to merge '{head}' into '{base}': {response.status_code} - {response.text}")
    return False


def delete_branch(name):
    response = gh_request("DELETE", f"git/refs/heads/{quote(name, safe='/')}")
    if response.status_code != 204:
        logger.warning(f"GitHub: Failed to delete branch '{name}': {response.status_code} - {response.text}")
        return False
    return True
