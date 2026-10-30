# brit-pollen-trays

Aggregate and analyze BRIT pollen tray images: download from Dropbox, organize,
then segmentation and OCR.

## Layout

- `scripts/download_dropbox.sh` — sync images from Dropbox with rclone
- `src/brit_pollen_trays/` — package code (manifest, later segmentation and OCR)
- `data/raw/` — downloaded images (not tracked in git)
- `data/interim/`, `data/processed/` — derived outputs (not tracked in git)
- `notebooks/` — exploration

## Workflow

```bash
uv sync
rclone config                                   # once: add a "dropbox" remote
scripts/download_dropbox.sh "<Dropbox folder>" --dry-run
scripts/download_dropbox.sh "<Dropbox folder>"
uv run pollen-manifest                          # writes data/interim/manifest.csv
```

OCR uses the system `tesseract` binary via `pytesseract`.

## Textract (handwriting / small text)

```bash
uv run pollen-textract --limit 5     # try a few first; responses cached in data/interim/textract/
```

Needs AWS credentials (`aws configure` or SSO). Images are sent to AWS, and
Textract is billed per page, so check pricing and data-sharing policy first.
