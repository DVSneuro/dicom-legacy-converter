# dicom-legacy-converter

Small Python package for converting Siemens-style Enhanced MR multi-frame DICOM
objects into classic single-frame MR DICOM files for older PACS workflows.

The immediate target is the failure mode where a PACS shows one image from an
Enhanced MR object instead of the full slice stack. The converter writes one
classic `MR Image Storage` DICOM file per frame and places the result in a new
derived series while preserving the original study.

## Clinical and operational guardrails

This is an interoperability helper, not a diagnostic image processing pipeline.
Before sending converted images for clinical reading:

- test with a non-expiring case first;
- verify the output in an independent DICOM viewer;
- confirm slice count, orientation, spacing, order, and patient/study identity;
- keep the original Enhanced MR files unchanged;
- document that the uploaded series is a compatibility conversion.

The converter does not anonymize data.

## Install

This package is intended for a Linux or Linux-like shell environment, such as
Linux, macOS Terminal, or Windows Subsystem for Linux. The commands below assume
that `git`, `python3`, and `pip` are available.

Clone the repository, enter it, create a virtual environment, and install the
command-line tool:

```bash
git clone https://github.com/DVSneuro/dicom-legacy-converter.git
cd dicom-legacy-converter
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
```

Activating the virtual environment is what puts the `dicom-legacy` command on
your `PATH`. If you do not want to activate the environment, call the command
through its full path instead:

```bash
.venv/bin/dicom-legacy --help
```

If installation fails with an error like `could not create
src/dicom_legacy_converter.egg-info: Permission denied`, the checkout is not
writable by your user. The easiest fix is usually to clone a fresh copy into a
directory you own. You can also check ownership with:

```bash
ls -ld . src
```

If the files are owned by another user, move the repo aside and clone it again
as your own user. Avoid running `pip` with `sudo` inside the virtual
environment.

If your input DICOMs use compressed transfer syntaxes, install the pixel decoder
plugins that match your scanner export, for example `pylibjpeg`,
`pylibjpeg-libjpeg`, or `pylibjpeg-openjpeg`.

## Recommended Workflow

For a large scanner export, start with a dry run. This scans the input and shows
which Enhanced MR series would be converted without writing any output files:

```bash
dicom-legacy /path/to/scanner_export /path/to/output_dir --recursive --dry-run --summary-only
```

If the export contains task/rest fMRI, a cautious dry run is:

```bash
dicom-legacy /path/to/scanner_export /path/to/output_dir --recursive --dry-run --summary-only --skip-bold --max-series-frames 300
```

If the summary looks reasonable, run the real conversion into a fresh output
directory:

```bash
dicom-legacy /path/to/scanner_export /path/to/output_dir --recursive --skip-bold --max-series-frames 300
```

If you only want structural images for clinical review, inspect the dry-run
summary and consider excluding field maps or other non-diagnostic support
series:

```bash
dicom-legacy /path/to/scanner_export /path/to/output_dir --recursive --skip-bold --max-series-frames 300 --exclude-regex "fmap|field[_ -]?mapping"
```

After conversion, open the output in a DICOM viewer and check patient/study
identity, series identity, slice count, orientation, spacing, and image order
before uploading for review.

## Examples

Convert one Enhanced MR file:

```bash
dicom-legacy /path/to/enhanced_mr.dcm /path/to/output_dir
```

Convert every DICOM found under a folder:

```bash
dicom-legacy /path/to/scanner_export /path/to/output_dir --recursive
```

By default, existing output files are not overwritten:

```bash
dicom-legacy /path/to/enhanced_mr.dcm /path/to/output_dir --overwrite
```

You can also run the CLI as a Python module from the installed environment:

```bash
python -m dicom_legacy_converter /path/to/enhanced_mr.dcm /path/to/output_dir
```

## CLI Options

| Option | Meaning |
| --- | --- |
| `--recursive` | Search all subfolders under the input directory. |
| `--dry-run` | Scan inputs and report what would happen without writing files. |
| `--summary-only` | With `--dry-run`, print aggregate summaries instead of per-source lines. |
| `--skip-bold` | Skip likely BOLD/fMRI/rest/task series based on path and DICOM metadata. |
| `--exclude-regex REGEX` | Skip sources whose path or selected DICOM metadata match a custom pattern. |
| `--max-series-frames N` | Skip any original DICOM series that would produce more than `N` output files. |
| `--overwrite` | Allow replacing existing output files. |
| `--copy-single-frame` | Copy non-enhanced single-frame DICOMs into the output directory too. |
| `--progress-interval PERCENT` | Report progress every `PERCENT` percent. Default is `10`. |
| `--quiet` | Suppress progress updates. |
| `--verbose` | Print per-source skipped files instead of only a skipped summary. |
| `--force` | Pass `force=True` to `pydicom.dcmread` for non-standard files. |

The CLI reports progress to stderr by default. It reports source-file progress
and, for Enhanced MR files, frame-writing progress:

```text
Found 1 source file(s).
source files: 0% (0/1)
enhanced_mr.dcm: decoding pixel data (208 frame(s)).
enhanced_mr.dcm frames: 0% (0/208)
enhanced_mr.dcm frames: 10% (21/208)
```

Change the reporting interval or silence progress updates:

```bash
dicom-legacy /path/to/scanner_export /path/to/output_dir --recursive --progress-interval 5
dicom-legacy /path/to/scanner_export /path/to/output_dir --recursive --quiet
```

Skipped files are summarized by reason instead of printed one-by-one. Use
`--verbose` if you need a per-source skipped list:

```bash
dicom-legacy /path/to/scanner_export /path/to/output_dir --recursive --skip-bold --verbose
```

The dry run reports Enhanced MR source files grouped by original DICOM series.
This helps catch functional runs that would expand into thousands of output
files.

Skip likely BOLD/fMRI/rest/task series:

```bash
dicom-legacy /path/to/scanner_export /path/to/output_dir --recursive --skip-bold
```

Skip any source whose path or selected DICOM metadata match a custom pattern:

```bash
dicom-legacy /path/to/scanner_export /path/to/output_dir --recursive --exclude-regex "bold|fmri|rest|task"
```

Skip original DICOM series that would generate more than a chosen number of
single-frame output files:

```bash
dicom-legacy /path/to/scanner_export /path/to/output_dir --recursive --max-series-frames 300
```

For exports that contain task/rest fMRI, a cautious first conversion is:

```bash
dicom-legacy /path/to/scanner_export /path/to/output_dir --recursive --skip-bold --max-series-frames 300
```

## Developer Checks

`pytest` runs the package's automated tests. It is for developers, maintainers,
or anyone who wants to verify that the local installation works. You do not need
to run `pytest` after each DICOM conversion.

```bash
python -m pip install -e ".[test]"
pytest
```

## What it converts

This first version is intentionally conservative. It supports uncompressed
Enhanced MR images with a standard `PerFrameFunctionalGroupsSequence` and writes
classic single-frame `MR Image Storage` instances.

For each frame it copies the pixel data and maps common per-frame metadata:

- `ImagePositionPatient`
- `ImageOrientationPatient`
- `PixelSpacing`
- `SliceThickness`
- `SpacingBetweenSlices`
- `ImageType` from Enhanced MR frame type
- `RescaleSlope`, `RescaleIntercept`, and window settings when present
- `EchoTime`, `RepetitionTime`, and `FlipAngle` when present in functional groups

The output keeps `StudyInstanceUID`, creates a new `SeriesInstanceUID`, and
creates a new `SOPInstanceUID` for each single-frame DICOM.

Output folders are named from readable source context when available:

- DICOM `SeriesNumber`
- DICOM `SeriesDescription`
- DICOM `ProtocolName`
- the original input parent folder name
- a short source-specific suffix to avoid collisions

For example, a converted T1 series may look like:

```text
3_T1_MPRAGE_anat_T1w_original_mprage_folder_1.2.3.4.5/
```

## Known limitations

- Only MR is targeted.
- Pixel data is written as uncompressed Explicit VR Little Endian.
- Private Siemens tags are copied as-is unless they are part of removed
  enhanced multi-frame structures.
- This does not perform conformance validation against every Type 1/2 element
  required by the classic MR Image IOD.
- Some legacy PACS installations have site-specific expectations. If NDI can
  share a sample accepted DICOM, compare the tags from this converter against it.

## Acknowledgments

Initial package scaffolding, CLI implementation, and synthetic test generation
were prepared with assistance from OpenAI Codex.
