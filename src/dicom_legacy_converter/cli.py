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
        "--dry-run",
        action="store_true",
        help="Scan inputs and report what would be converted without writing files",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print aggregate dry-run summary without per-source result lines",
    )
    parser.add_argument(
        "--skip-bold",
        action="store_true",
        help="Skip series whose path or metadata look like BOLD/fMRI/rest/task data",
    )
    parser.add_argument(
        "--exclude-regex",
        metavar="REGEX",
        help="Skip inputs whose path or selected DICOM metadata match REGEX",
    )
    parser.add_argument(
        "--max-series-frames",
        type=int,
        metavar="N",
        help=(
            "Skip original DICOM series that would produce more than N "
            "single-frame output files"
        ),
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
    if args.summary_only and not args.dry_run:
        parser.error("--summary-only can only be used with --dry-run")

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
            dry_run=args.dry_run,
            skip_bold=args.skip_bold,
            exclude_regex=args.exclude_regex,
            max_series_frames=args.max_series_frames,
        )
    except ConversionError as exc:
        parser.error(str(exc))

    converted_count = 0
    output_count = 0
    would_write_count = 0
    skipped_count = 0
    for result in results:
        if result.converted:
            converted_count += 1
            output_count += len(result.output_files)
        elif result.message.startswith("would write "):
            would_write_count += 1
        elif result.message.startswith("would copy "):
            would_write_count += 1
        else:
            skipped_count += 1

        if args.summary_only:
            continue

        if result.converted:
            status = "converted"
        elif result.message.startswith("would "):
            status = "would convert"
        else:
            status = "skipped"
        print(f"{status}: {result.source} - {result.message}")

    if args.dry_run:
        print(
            "Dry run complete. "
            f"{would_write_count} source file(s) would be written/copied; "
            f"{skipped_count} source file(s) would be skipped. "
            "No files were written."
        )
    else:
        print(
            f"Done. Converted {converted_count} source file(s) "
            f"into {output_count} DICOM file(s)."
        )
    return 0


def _print_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
