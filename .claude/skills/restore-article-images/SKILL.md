---
name: restore-article-images
description: Restore the images of an Astro article of the GdG Event Bot that went live without images or with broken image links, usually because the R2 uploads failed while it was generated. Uploads the night's images from the data folder to R2 and, if the article has no images at all, regenerates it. Use when an article page shows no pictures, its image URLs return 404, or the user says the R2 upload failed for a night.
---

# Restore an article's images

Two scripts do the work, run from the repository root on the machine that has the **real `data/` folder and `.env`** (the server). If `data/` here is empty or has no database, say so and give the user the commands instead of running them. Never print tokens or keys.

- `scripts/sync_images_to_r2.py <DD-MM-YYYY>`: uploads a night's images (loose or inside the nightly `archive.zip`) to R2 under the keys the article uses. It never writes to the database or the article.
- `scripts/regenerate_article.py <DD-MM-YYYY>`: rebuilds the article from the events in the database, reusing the images already in R2. The cover is `--cover`, else the existing article's cover, else the **newest collage** of the night if it is already in R2.

Dates are the night's date, e.g. `30-10-2026`. The article is `src/content/serate/<YYYY-MM-DD>-<slug>.md` in the website repo (slug `eventi-della-serata-<giorno>-<dd-mm-yyyy>`).

## 1. Diagnose
Read the published article (or run `sync_images_to_r2.py <date> --dry-run` and look at what it reports) and find which case it is:

| Case | What you see | What to do |
|---|---|---|
| **A. No images at all** | no `cover`, no `immagine` in `tavoli`, no `![..](..)` on the R2 host. The uploads failed **while the article was generated**, so Gemini was never given image URLs. The sync script says "l'articolo non contiene immagini ospitate su ...". | Step 2 with `--all`, then step 3. |
| **B. Image URLs present, they 404** | the URLs point at `R2_PUBLIC_URL/serate/<slug>/...` but the files are not there. | Step 2 without `--all`. The article needs no change. |
| **C. URLs answer 200, the page still shows nothing** | files are in R2. | Not a file problem. Compare the URL host in the article with `R2_PUBLIC_URL`, and check the bucket's public access or custom domain. |

## 2. Upload the images
```
python3 scripts/sync_images_to_r2.py <DD-MM-YYYY> [--all] --dry-run
python3 scripts/sync_images_to_r2.py <DD-MM-YYYY> [--all]
```
- Show the dry run first: it lists what is already reachable, what would be uploaded and from which folder or zip, and what is not on disk.
- `--all` uploads every event image of the night and every `collage_*` file. Without it only the images the article references are uploaded. `--article-file FILE` reads the article from a local copy; `--force` re-uploads what is already reachable.
- **Read any upload error: it is the real cause of the original failure.** An "uploaded but not reachable" warning points at the bucket's public access or `R2_PUBLIC_URL`, not at a missing file.
- Exit code 1 means something is still missing or unreachable. Do not go on to step 3 until it is 0.

## 3. Regenerate the article (case A)
```
python3 scripts/regenerate_article.py <DD-MM-YYYY> --dry-run --output /tmp/<DD-MM-YYYY>.md
python3 scripts/regenerate_article.py <DD-MM-YYYY>
python3 scripts/regenerate_article.py <DD-MM-YYYY> --publish
```
- The dry run writes the whole file locally; read it. Check that every game has its image, the cover is set and the layout is right (plain intro, one `###` section per event, `---`, closing).
- Without `--dry-run` it creates or updates the draft branch `serata/<slug>` on the website repo and prints the link, so the result can be read on GitHub.
- `--publish` also merges the branch, which **deploys the site**. Only run it after the user has confirmed.
- If it says the newest collage is not on R2, run step 2 with `--all` first. Use `--cover URL` to pick a different collage.

## Why uploads fail (so it does not repeat)
- `boto3` not installed in the bot's virtualenv: `pip install -r requirements.txt` and restart (the bot logs a warning at startup when it is missing).
- Missing `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` or `R2_PUBLIC_URL` in `.env`.
- An R2 API token without *Object Read & Write* on `R2_BUCKET`.
- `R2_PUBLIC_URL` that does not serve the bucket (public access off, wrong custom domain).

## Rules
1. Dry run first, every time, and show it to the user.
2. `--publish` and any push to the website repo deploy the site: get a yes first.
3. Do not edit the article by hand when the scripts can regenerate it.
4. Both scripts only read the database; neither changes the bot's data.
