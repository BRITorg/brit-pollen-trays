# brit-pollen-trays

Aggregate and analyze BRIT pollen tray images: download from Dropbox, organize,
then segmentation and OCR.

## Layout

- `scripts/download_dropbox.sh` — optional: re-sync JPGs from Dropbox with rclone (CR2 excluded); not needed to use the repo
- `src/brit_pollen_trays/` — `manifest.py` (image index), `textract.py` (OCR passes),
  `slots.py` (per-slide table)
- `docs/ocr-process.md` — how OCR works here, what we tried, accuracy and open issues
- `data/raw/` — the 129 source JPGs, tracked in git (6 session folders, ~837 MB)
- `data/interim/`, `data/processed/` — derived outputs (not tracked in git)
- `notebooks/` — exploration

## Workflow

```bash
git clone <repo>                      # images in data/raw come with the clone (~837 MB)
uv sync
uv run pollen-manifest                                  # data/interim/manifest.csv
uv run pollen-textract --profile <aws-profile>          # two passes, cached JSON
uv run pollen-slots                                     # data/processed/slots.csv
```

Needs AWS credentials with Textract access (only to re-run OCR) and Python 3.11+ with [uv](https://docs.astral.sh/uv/). Images are sent to AWS
Textract and billed per page, so check your data-sharing policy first. See
`docs/ocr-process.md` for details and current accuracy.
