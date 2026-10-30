# brit-pollen-trays

Aggregate and analyze BRIT pollen tray images: download from Dropbox, organize,
then segmentation and OCR.

## Layout

- `scripts/download_dropbox.sh` — sync JPGs from Dropbox with rclone (CR2 excluded)
- `src/brit_pollen_trays/` — `manifest.py` (image index), `textract.py` (OCR passes),
  `slots.py` (per-slide table)
- `docs/ocr-process.md` — how OCR works here, what we tried, accuracy and open issues
- `data/raw/` — downloaded images (not tracked in git)
- `data/interim/`, `data/processed/` — derived outputs (not tracked in git)
- `notebooks/` — exploration

## Workflow

```bash
uv sync
scripts/download_dropbox.sh "<Dropbox folder>" --dry-run
scripts/download_dropbox.sh "<Dropbox folder>"
uv run pollen-manifest                                  # data/interim/manifest.csv
uv run pollen-textract --profile <aws-profile>          # two passes, cached JSON
uv run pollen-slots                                     # data/processed/slots.csv
```

Needs `rclone` with a Dropbox remote (`rclone config`), AWS credentials with Textract
access, and Python 3.11+ with [uv](https://docs.astral.sh/uv/). Images are sent to AWS
Textract and billed per page, so check your data-sharing policy first. See
`docs/ocr-process.md` for details and current accuracy.
