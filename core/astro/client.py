import requests

from core import config

REQUEST_TIMEOUT = 30


def github_credentials():
    """(repo, headers) for the GitHub API, or None when the token is not configured."""
    if not (config.ASTRO_GITHUB_REPO and config.ASTRO_GITHUB_TOKEN):
        return None
    headers = {
        "Authorization": f"Bearer {config.ASTRO_GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    return config.ASTRO_GITHUB_REPO, headers


def gh_request(method, path, **kwargs):
    """Calls https://api.github.com/repos/<repo>/<path>; raises RuntimeError when GitHub is not configured."""
    creds = github_credentials()
    if not creds:
        raise RuntimeError("GitHub credentials not configured")
    repo, headers = creds
    return requests.request(
        method, f"https://api.github.com/repos/{repo}/{path}",
        headers=headers, timeout=REQUEST_TIMEOUT, **kwargs,
    )


def r2_client():
    """boto3 S3 client for the R2 bucket, or None when R2 is not fully configured."""
    if not (config.R2_ACCOUNT_ID and config.R2_ACCESS_KEY_ID and config.R2_SECRET_ACCESS_KEY
            and config.R2_BUCKET and config.R2_PUBLIC_URL):
        return None
    import boto3  # imported lazily: only needed by the astro backend

    return boto3.client(
        "s3",
        endpoint_url=f"https://{config.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        region_name="auto",
        aws_access_key_id=config.R2_ACCESS_KEY_ID,
        aws_secret_access_key=config.R2_SECRET_ACCESS_KEY,
    )
