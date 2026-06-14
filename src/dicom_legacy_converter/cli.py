from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .convert import ConversionError, convert_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dicom-legacy",
        description=(
            "Convert Enhanced MR multi-frame DICOM objects into classic "
            "single-frame MR DICOM files."
        ),
    )
    parser.add_argument("input", type=Path, help="DICOM file or directory to convert")
    parser.add_argument("output", type=Path, help="Directory for converted files")
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search input directories recursively",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing converted DICOM files",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Pass force=True to pydicom.dcmread for non-standard files",
    )
    parser.add_argument(
        "--copy-single-frame",
        action="store_true",
        help="Copy classic single-frame DICOMs into the output directory too",
    )
    parser.add_argument(
        "--progress-interval",
        type=int,
        default=10,
        metavar="PERCENT",
        help="Report progress every PERCENT percent (default: 10)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress updates",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        results = convert_path(
            args.input,
            args.output,
            recursive=args.recursive,
            overwrite=args.overwrite,
            force=args.force,
            copy_single_frame=args.copy_single_frame,
            progress=None if args.quiet else _print_progress,
            progress_interval=args.progress_interval,
        )
    except ConversionError as exc:
        parser.error(str(exc))

    converted_count = 0
    output_count = 0
    for result in results:
        if result.converted:
            converted_count += 1
            output_count += len(result.output_files)
        status = "converted" if result.converted else "skipped"
        print(f"{status}: {result.source} - {result.message}")

    print(f"Done. Converted {converted_count} source file(s) into {output_count} DICOM file(s).")
    return 0


def _print_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
