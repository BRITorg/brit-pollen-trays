# brit-pollen-trays

Photos of BRIT pollen slide trays, and a pipeline that turns them into a table with
one row per slide: its sticker ID, tray, slot number and label text.

Each photo shows one or two aluminum trays of 20 microscope slides. The pipeline reads
the printed sticker IDs and label text with AWS Textract (OCR), and uses the IDs to
locate each slide. The repo holds 129 photos from one station, taken 2019-07-16 to
2019-07-31 (4,980 slide positions).

**Status:** the pipeline finds 4,859 of 4,980 expected slides (97.6%). Label text is raw,
unvalidated OCR and sometimes bleeds into the neighbouring slide. See
[`docs/ocr-process.md`](docs/ocr-process.md) for the method, what we tried, current
accuracy and the open issues.

## Layout

- `data/raw/` — the 129 source JPGs, tracked in git (6 session folders, ~837 MB)
- `data/interim/`, `data/processed/` — derived outputs, not tracked in git, except
  `data/processed/slots.csv` and the viewer (`data/processed/viewer/index.html` and its
  `crops/`)
- `src/brit_pollen_trays/`
  - `manifest.py` — index of the images (size, dimensions, checksum)
  - `textract.py` — runs Textract passes and caches the raw responses
  - `slots.py` — builds the per-slide table from the cached responses
  - `viewer.py` — builds a static HTML page for checking labels against slide crops
- `docs/ocr-process.md` — OCR method, evidence, accuracy and ideas for improvement
- `scripts/download_dropbox.sh` — optional: re-sync the JPGs from BRIT's Dropbox with
  rclone (CR2 raw files excluded). Not needed, since the images are in the repo.

## Running it

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). A clone includes the images
(~837 MB).

```bash
uv sync
uv run pollen-manifest                           # -> data/interim/manifest.csv
uv run pollen-textract --profile <aws-profile>   # -> data/interim/textract/*.json
uv run pollen-slots                              # -> data/processed/slots.csv
uv run pollen-viewer                             # -> data/processed/viewer/index.html
```

`pollen-textract` needs AWS credentials with Textract access. It runs two passes per image
(upright and rotated 90°), skips pages already cached, and stops cleanly if your SSO token
expires, so it is safe to interrupt and rerun. Images are sent to AWS and billed per page
(this dataset is 258 pages, well under $1), so check your data-sharing policy first.

`pollen-viewer` writes a crop per slide (~96 MB) and a page you open in a browser, with no
server needed. The page and crops are tracked in git, so after cloning you can just open
`data/processed/viewer/index.html`. Each slide shows beside its ID and OCR text, with the
estimated slide window drawn on the crop. Filter to likely errors (no label, hand-drawn
number disagrees, low ID confidence), mark rows correct or wrong, enter corrected text, and
export your review as CSV. Reviews are kept in your browser, so export before clearing it.

`slots.csv`, the crops and the page are committed. To rebuild `slots.csv` without re-running OCR, download the cached Textract responses from
the [`textract-2019-07-v1` release](https://github.com/BRITorg/brit-pollen-trays/releases/tag/textract-2019-07-v1)
(private repo, so you need access), unzip them into `data/interim/`, and run `pollen-slots`:

```bash
gh release download textract-2019-07-v1 -p textract_responses.zip
unzip textract_responses.zip -d data/interim/
uv run pollen-slots
```
Regenerating the crops changes ~95 MB of tracked files, so avoid committing them again
unless the slots or crop logic changed.

## Output

`data/processed/slots.csv` has one row per slide, with columns:

| Column | Meaning |
|---|---|
| `image`, `session` | source photo and its session folder |
| `tray`, `slot_number`, `sticker_id` | from the printed ID: tray prefix, slot 1-20, full ID |
| `id_x`, `id_y`, `id_conf` | where the ID sits in the upright image (0-1) and its OCR confidence |
| `label_text`, `label_has_handwriting`, `label_pass` | label text, whether any of it is handwritten, and which pass it came from |
| `hand_number`, `hand_number_matches_id` | hand-drawn slot numeral when Textract read one, and whether it agrees with the ID. Unreliable: 31% disagree, mostly from neighbouring-slide bleed |
| `slide_offset`, `slide_width` | estimated slide window used for assignment |

`data/processed/images_summary.csv` has one row per image with its slot and tray counts.
