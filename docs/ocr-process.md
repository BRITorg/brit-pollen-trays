# OCR process and accuracy notes

How we extract slide IDs and label text from the pollen tray photos, what we tried,
what the evidence says, and where accuracy still needs work. Numbers below come from
the 129 JPGs downloaded so far (6 sessions, 2019-07-16 to 2019-07-31). Where a claim
rests on a handful of images rather than a measurement over all of them, it says so.

## The images

- Each photo shows one or two aluminum trays of microscope slides. A tray holds 20
  slides in two columns of 10; a two-tray photo has 40 slides. 120 images have two
  trays and 9 have one (the single tray sits in the right-hand position).
- Each slide has a **printed sticker ID** (e.g. `72517`, `102511`): a tray prefix plus a
  two-digit slot number 01-20. It also has a hand-drawn slot number (1-20, marker) and a
  typed, printed or handwritten taxon label. Some slides also carry a pencilled copy of
  the ID next to the sticker.
- A color card and cm scale are fixed along the left edge.
- Images are 5616x3744 and are **stored rotated 180 degrees with EXIF orientation 3**
  (all 129). OpenCV applies the tag on load; PIL does not. Anything that reads pixels
  must apply it (`ImageOps.exif_transpose`), including what we send to Textract.
- Sticker IDs are printed **vertically** in the upright image.

## Pipeline

1. **Images.** The 129 JPGs are in `data/raw/` in this repo. They came from BRIT's
   Dropbox (`scripts/download_dropbox.sh`; CR2 raw files are excluded).
2. **Manifest** (`pollen-manifest`): path, size, dimensions and SHA-256 per image.
3. **Textract, two passes per image** (`pollen-textract`, AWS Textract
   `DetectDocumentText`, synchronous API, JPEG/PNG up to 10 MB):
   - upright pass (EXIF rotation baked in);
   - 90-degree clockwise pass, which makes the vertical sticker IDs horizontal.

   Raw responses are cached as JSON in `data/interim/textract/` so each page is billed
   once. Rotated responses carry a `.cw90` suffix.
4. **Slot table** (`pollen-slots`, `src/brit_pollen_trays/slots.py`) builds
   `data/processed/slots.csv`, one row per slide:
   - **Anchors:** sticker IDs from either pass. A valid ID is 5-6 digits whose last two
     digits are 01-20; a prefix needs at least 8 IDs in the image to count as a tray.
     The printed instance is preferred over a pencilled copy, then the higher
     confidence.
   - **Slide window:** the slide's horizontal extent is estimated per image from the
     anchor spacing, with an offset chosen to minimise text lines that cross slide
     edges (slides are physically separate, so text rarely straddles one).
   - **Label text:** lines inside a slide's window and row band are joined. Each slide
     takes text from whichever pass read more text there.
   - **Hand-drawn number:** a 1-20 numeral read as its own word in the window, stored
     separately from the ID-derived `slot_number` as a cross-check.

Coordinates in `slots.py` are normalised to the upright image. The rotated pass is
converted back: `left = top'`, `top = 1 - (left' + width')`, `width = height'`,
`height = width'`.

## Method details: preparing images for Textract

`image_bytes()` in `src/brit_pollen_trays/textract.py` builds each upload:

1. Open the JPG and apply the EXIF orientation (`ImageOps.exif_transpose`). The stored
   pixels are rotated 180 degrees, and we do not rely on Textract to honour the tag.
2. For the rotated pass, rotate a further 90 degrees clockwise (`im.rotate(-90,
   expand=True)`). A 90 degree rotation only moves pixels, so nothing is resampled.
   Sticker IDs, printed vertically, become horizontal lines.
3. Re-encode as JPEG at quality 95. If the result exceeds Textract's 10 MB limit, drop
   quality in steps of 10 to 70, then downscale by 20% and repeat. In practice a full
   5616x3744 image is 3.7-5.4 MB at quality 95 (median 5.0 MB, measured on all 129), so
   none of them has needed either fallback. Rotation does not change the size.

Responses come back in coordinates normalised to the image that was uploaded. For the
rotated pass `slots.py` maps them back to upright coordinates (formula above). We
checked the mapping by comparing IDs found in both passes: they land at identical
positions.

Direction was chosen by one test: clockwise recovered 40/40 IDs on the hardest test
image and counter-clockwise 39/40. That is not a meaningful difference, and
counter-clockwise would likely work as well. Clockwise was kept because it was tried
first.

## Why OCR anchors instead of segmenting and cropping slides

The obvious design is to detect each slide, crop it, and run OCR on each crop. We tried
the first half of that and dropped it. The reasoning, so collaborators don't have to
rediscover it:

- **What we tried:** register each tray against a reference image, then lay a fixed 2x10
  grid at that position. We used three registration methods in turn: ECC on gradient
  maps, 2D template matching, and 1D cross-correlation of edge profiles against a
  single-tray reference.
- **Why it failed:** the trays are placed by hand, so the two trays in a photo move
  independently by tens of pixels, and the right tray is not at a fixed offset from the
  left. The slot content (labels, mounts, colors, background) differs enough between
  sessions that edge-based matching latched onto the wrong structure, and the 10-row
  pattern repeats, which makes 2D matching ambiguous. Fits were confidently wrong on
  many images, and some overlapped.
- **Why OCR anchors worked better here:** we needed Textract anyway for the text. It
  returns a bounding box for every word, so the printed sticker IDs give each slide's
  position directly with no registration, and the ID also says which tray and slot it
  is. That removed the hardest problem (finding where the slides are) and added a
  built-in identity check (each tray should yield IDs 01-20).
- **Cost of the choice:** it is still a geometry estimate. We infer a slide's extent
  from anchor spacing rather than detect its edges, which is why labels and hand-drawn
  numerals can bleed into the neighbouring slide (see Current results). Segmentation
  would not have escaped that problem, but a crop per slide would have made the
  failure easier to see.
- **What we did not try:** direct detection of slide edges (e.g. Hough lines or
  rectangle detection on the glass), a trained or promptable segmentation model, or
  detecting the semicircular finger notches that appear on every slide. Any of these
  might beat our registration attempts. We moved on once the OCR approach gave 97.6%
  slot coverage.
- **Where cropping still helps:** once anchors give approximate slide positions, crops
  around them are a good way to re-read hard slides at full resolution and to build a
  review page for checking label accuracy (see ideas 2 and 4 below).

## What we tried, and what the evidence says

### Rotating the image 90 degrees
On three test images (pale spots, typed labels, handwritten labels with colored mounts),
a full-image 90 degree CW pass recovered all sticker IDs (20/20, 40/40, 40/40) while the
upright pass recovered 20, 40 and 25. That looked like a clear win for rotation.

Over all 129 images it is not. ID-shaped tokens found: upright 5,203, rotated 5,278,
union 5,428. The rotated pass found more on 34 images, fewer on 43, and the same on 52.
The three-image test happened to include the one unusual case (below). **Treat the two
passes as complementary and use both.** These counts include a few non-sticker numbers
(collection numbers), so they overstate IDs slightly.

### A pass can silently drop part of an image
On `BRIT_2019-07-31_S3_00143.JPG` the upright full-image pass returned no text at all
for the left tray (144 lines vs 299 from the rotated pass). Tiling the image into
left/right halves at full resolution also recovered it. Across all images this is rare:
only one image has fewer than 0.7x the lines of the other pass. We don't know why it
happened. Checking line counts per pass is a cheap guard.

### Tiling into tray halves
On the three test images, halves recovered the same IDs as one rotated full-image pass,
at twice the pages. Not adopted: it doubles the cost and splits any text that crosses the seam.

### Grid registration instead of OCR anchors (did not work)
Registering each tray and cropping a fixed grid gave confidently wrong fits on many
images (47 of 249 tray fits scored below our own reliability cutoff, and the worst
overlapped). See "Why OCR anchors instead of segmenting and cropping slides" above.
The prototype is not in the repo.

### Handwriting
Textract reports `TextType: HANDWRITING` on WORD blocks, not LINE blocks; a line is
treated as handwritten if any of its words is. Handwritten label lines are read, with
mixed accuracy (`Trixis`, `inula`, `Lentibulariaceae` correct; `Theles perma`,
`RHUINT` damaged, from a spot check). We have **not** measured label accuracy.

The large marker numerals (1-20) are read only some of the time.

## Current results

- **Slots found: 4,859 of 4,980 expected (97.6%).** 83 images have a full 40, 6 have a
  full 20; 40 images are short, mostly by one slot, spread evenly over slot numbers 1-20.
- `BRIT_2019-07-24_S3_00060.JPG` yields 0 slots; its IDs appear to use a different
  numbering (several above 20), which our validity rule rejects.
- No image has a duplicated ID. All 129 have both passes.
- 68 slots have no label text; 1,831 took their text from the rotated pass.
- **Hand-drawn numbers:** read in 2,098 slots; 1,450 agree with the ID-derived number
  and 648 (31%) do not. 427 of the 648 are off by exactly 10, which suggests our slide
  windows sometimes pull in the numeral from the neighbouring slide in the same row.
  That is probably a geometry error on our side, not an OCR error. **Label text likely
  has the same bleed.** Treat `label_text` as raw, unvalidated OCR.

## Ideas to improve accuracy

Roughly in order of expected value, none yet done:

1. **Fix slide-boundary bleed.** Tighten windows, assign lines by their extent rather than
   their centre, or accept a hand-drawn numeral only if it matches the slot. Re-measure
   the hand-number agreement; a large jump above 69% would confirm the windows were the
   cause.
2. **Build a small validation set.** Hand-transcribe labels for ~50 randomly chosen slots
   across all sessions, and report character- and word-level accuracy per session and per
   label style (typed / printed form / handwritten). Without this, "improved" means
   nothing.
3. **Use known structure.** Expected IDs per tray are a fixed set (prefix + 01-20), so
   missing or misread IDs can be inferred from neighbours; ID rows also constrain
   position. Cross-check IDs against the collection database where one exists.
4. **Re-read problem slides at full resolution.** Crop each slide from the full 5616x3744
   image around its anchor and send crops to Textract, rather than relying on a
   whole-tray read in which small text is a few pixels tall.
5. **Fuzzy-match taxon names** against a name source (e.g. a taxonomic backbone) to
   correct near-miss OCR such as `Theles perma` -> *Thelesperma*. The `gnfinder` tool is
   one option.
6. **Compare engines** (e.g. Tesseract for printed text, a handwriting-specific model)
   on the validation set before committing to one.
7. **Image preprocessing** (contrast, deskew, glare reduction on the aluminum) is
   untested.
8. **COCO export of image regions.** Write a COCO JSON with one bounding box per slide,
   sticker ID and label-text region (OCR text and confidence as extra attributes). Useful
   for (a) loading our boxes into an annotation tool such as CVAT, Label Studio or
   Roboflow as pre-annotations that people correct, and (b) training or fine-tuning a
   detector or segmenter to replace the anchor-window estimate behind the bleed in
   idea 1. Cautions: our slide boxes are estimates, not detected edges, so they should be
   human-corrected before training on them; we have boxes only, no polygons or masks
   (those would need a model such as SAM, or manual drawing); and all images are stored
   rotated 180 degrees with an EXIF tag, which some loaders apply and others ignore, so
   the file must state whether boxes are in stored-pixel or upright coordinates (or ship
   upright copies of the images). Not needed if the goal is only the slot table and label
   text.

## Reproducing

```bash
uv sync                                              # images are already in data/raw
uv run pollen-manifest
aws sso login --sso-session <your-session>          # whatever your AWS SSO setup is
uv run pollen-textract --profile <aws-profile> --rotations 0 90
uv run pollen-slots
```

`pollen-textract` skips pages already cached, so it is safe to interrupt and rerun, and it
stops cleanly if your SSO token expires. `--limit N` processes at most N new pages.

**Cost and data sharing.** Textract is billed per page (list price about $1.50 per 1,000
pages; this dataset is 258 pages, under $0.50). Images are sent to AWS, so check your
institution's policy before running it on new material.

## Known limitations

- Everything above is from one batch of 129 images from one station and one month.
- Coordinates and slide geometry assume the current tray design (2 columns x 10 rows,
  stickers vertical).
- `data/raw/` (the images) is in git, but outputs in `data/interim/` and `data/processed/`
  are not, including the Textract responses. Re-running `pollen-textract` needs your own
  AWS access; ask the maintainers for the zipped responses to skip it.
