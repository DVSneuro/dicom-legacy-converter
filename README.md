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

From this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
```

Activating the virtual environment is what puts the `dicom-legacy` command on
your `PATH`. If you do not want to activate the environment, call the command
through its full path instead:

```bash
.venv/bin/dicom-legacy --help
```

If your input DICOMs use compressed transfer syntaxes, install the pixel decoder
plugins that match your scanner export, for example `pylibjpeg`,
`pylibjpeg-libjpeg`, or `pylibjpeg-openjpeg`.

## Use

Convert one Enhanced MR file:

```bash
dicom-legacy /path/to/enhanced_mr.dcm /path/to/output_dir
```

Convert every DICOM found under a folder:

```bash
dicom-legacy /path/to/scanner_export /path/to/output_dir --recursive
```

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

By default, existing output files are not overwritten:

```bash
dicom-legacy /path/to/enhanced_mr.dcm /path/to/output_dir --overwrite
```

Run tests:

```bash
pytest
```

You can also run the CLI as a Python module from the installed environment:

```bash
python -m dicom_legacy_converter /path/to/enhanced_mr.dcm /path/to/output_dir
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
