from __future__ import annotations

import copy
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pydicom
from pydicom.datadict import tag_for_keyword
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.errors import InvalidDicomError
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, PYDICOM_IMPLEMENTATION_UID, UID, generate_uid

ENHANCED_MR_IMAGE_STORAGE = UID("1.2.840.10008.5.1.4.1.1.4.1")
MR_IMAGE_STORAGE = UID("1.2.840.10008.5.1.4.1.1.4")

ENHANCED_ONLY_KEYWORDS = (
    "NumberOfFrames",
    "SharedFunctionalGroupsSequence",
    "PerFrameFunctionalGroupsSequence",
    "DimensionIndexSequence",
    "DimensionOrganizationSequence",
    "ConcatenationUID",
    "InConcatenationNumber",
    "InConcatenationTotalNumber",
    "RepresentativeFrameNumber",
)


class ConversionError(RuntimeError):
    """Raised when a DICOM file cannot be converted safely."""


@dataclass(frozen=True)
class ConversionResult:
    source: Path
    converted: bool
    output_files: tuple[Path, ...]
    message: str


def convert_path(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    recursive: bool = False,
    overwrite: bool = False,
    force: bool = False,
    copy_single_frame: bool = False,
) -> list[ConversionResult]:
    """Convert Enhanced MR DICOM files found at *input_path*.

    Parameters
    ----------
    input_path
        A DICOM file or a directory containing DICOM files.
    output_dir
        Directory where converted files should be written.
    recursive
        If true, recursively search directories.
    overwrite
        If true, replace existing converted files.
    force
        If true, pass ``force=True`` to ``pydicom.dcmread``.
    copy_single_frame
        If true, copy non-enhanced DICOM files into the output directory.
    """

    input_path = Path(input_path)
    output_dir = Path(output_dir)
    if not input_path.exists():
        raise ConversionError(f"Input path does not exist: {input_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[ConversionResult] = []

    for source in _iter_input_files(input_path, recursive=recursive):
        ds = _read_dicom_or_none(source, force=force)
        if ds is None:
            results.append(
                ConversionResult(source, False, tuple(), "not a readable DICOM file")
            )
            continue

        if is_enhanced_mr(ds):
            files = split_enhanced_mr_dataset(
                ds,
                source,
                output_dir,
                overwrite=overwrite,
            )
            results.append(
                ConversionResult(
                    source,
                    True,
                    tuple(files),
                    f"wrote {len(files)} classic MR instance(s)",
                )
            )
            continue

        if copy_single_frame:
            copied = _copy_single_frame(source, output_dir, overwrite=overwrite)
            results.append(
                ConversionResult(source, True, (copied,), "copied existing single-frame DICOM")
            )
        else:
            sop_class = str(ds.get("SOPClassUID", "unknown SOP class"))
            results.append(
                ConversionResult(source, False, tuple(), f"not Enhanced MR ({sop_class})")
            )

    return results


def split_enhanced_mr_file(
    source: str | Path,
    output_dir: str | Path,
    *,
    overwrite: bool = False,
    force: bool = False,
) -> list[Path]:
    """Split one Enhanced MR file into classic single-frame MR DICOM files."""

    source = Path(source)
    ds = pydicom.dcmread(source, force=force)
    return split_enhanced_mr_dataset(ds, source, Path(output_dir), overwrite=overwrite)


def split_enhanced_mr_dataset(
    ds: Dataset,
    source: Path,
    output_dir: Path,
    *,
    overwrite: bool = False,
) -> list[Path]:
    if not is_enhanced_mr(ds):
        raise ConversionError(f"Not an Enhanced MR object: {source}")

    frame_count = _frame_count(ds)
    if frame_count < 1:
        raise ConversionError(f"Enhanced MR object has no frames: {source}")

    try:
        pixel_array = ds.pixel_array
    except Exception as exc:  # noqa: BLE001 - pydicom decoder errors vary by plugin
        raise ConversionError(
            "Unable to decode PixelData. If this file uses compressed pixel data, "
            "install the matching pydicom pixel data plugin."
        ) from exc

    series_uid = generate_uid()
    series_dir = output_dir / _series_folder_name(source)
    series_dir.mkdir(parents=True, exist_ok=True)

    output_files: list[Path] = []
    now = datetime.now()
    for frame_index in range(frame_count):
        out = _build_single_frame_dataset(
            ds,
            pixel_array,
            frame_index,
            frame_count,
            series_uid,
            now,
        )
        target = series_dir / f"IM_{frame_index + 1:04d}.dcm"
        if target.exists() and not overwrite:
            raise ConversionError(
                f"Output file already exists: {target}. Use --overwrite to replace it."
            )

        out.save_as(target, enforce_file_format=True)
        output_files.append(target)

    return output_files


def is_enhanced_mr(ds: Dataset) -> bool:
    """Return true when *ds* looks like an Enhanced MR multi-frame object."""

    sop_class = UID(str(ds.get("SOPClassUID", "")))
    if sop_class == ENHANCED_MR_IMAGE_STORAGE:
        return True

    return (
        str(ds.get("Modality", "")).upper() == "MR"
        and _frame_count(ds) > 1
        and hasattr(ds, "PerFrameFunctionalGroupsSequence")
    )


def _build_single_frame_dataset(
    source: Dataset,
    pixel_array: np.ndarray,
    frame_index: int,
    frame_count: int,
    series_uid: str,
    created_at: datetime,
) -> Dataset:
    out = copy.deepcopy(source)

    for keyword in ENHANCED_ONLY_KEYWORDS:
        _delete_keyword(out, keyword)

    out.SOPClassUID = MR_IMAGE_STORAGE
    out.SOPInstanceUID = generate_uid()
    out.SeriesInstanceUID = series_uid
    out.Modality = "MR"
    out.InstanceNumber = frame_index + 1
    out.ImagesInAcquisition = frame_count
    out.DerivationDescription = (
        "Converted from Enhanced MR multi-frame DICOM to classic single-frame "
        "MR Image Storage for PACS compatibility."
    )
    out.InstanceCreationDate = created_at.strftime("%Y%m%d")
    out.InstanceCreationTime = created_at.strftime("%H%M%S.%f")

    if hasattr(source, "SeriesDescription"):
        out.SeriesDescription = _truncate_long_string(
            f"{source.SeriesDescription} legacy single-frame"
        )

    _set_file_meta(out)
    _set_source_reference(out, source)
    _apply_functional_groups(out, source, frame_index)
    _set_pixel_data(out, pixel_array, frame_index, frame_count)
    _set_slice_location(out)

    return out


def _set_file_meta(ds: Dataset) -> None:
    ds.file_meta = FileMetaDataset()
    ds.file_meta.FileMetaInformationVersion = b"\x00\x01"
    ds.file_meta.MediaStorageSOPClassUID = MR_IMAGE_STORAGE
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    ds.file_meta.ImplementationVersionName = "DICOMLEGACY_01"


def _set_source_reference(out: Dataset, source: Dataset) -> None:
    item = Dataset()
    item.ReferencedSOPClassUID = source.SOPClassUID
    item.ReferencedSOPInstanceUID = source.SOPInstanceUID
    out.SourceImageSequence = Sequence([item])


def _apply_functional_groups(out: Dataset, source: Dataset, frame_index: int) -> None:
    shared = _sequence_item(source, "SharedFunctionalGroupsSequence", 0)
    per_frame = _sequence_item(source, "PerFrameFunctionalGroupsSequence", frame_index)
    groups = (shared, per_frame)

    _copy_group_attrs(
        out,
        groups,
        "PixelMeasuresSequence",
        (
            "PixelSpacing",
            "SliceThickness",
            "SpacingBetweenSlices",
        ),
    )
    _copy_group_attrs(
        out,
        groups,
        "PlaneOrientationSequence",
        ("ImageOrientationPatient",),
    )
    _copy_group_attrs(
        out,
        groups,
        "PlanePositionSequence",
        ("ImagePositionPatient",),
    )
    _copy_group_attrs(
        out,
        groups,
        "PixelValueTransformationSequence",
        (
            "RescaleIntercept",
            "RescaleSlope",
            "RescaleType",
        ),
    )
    _copy_group_attrs(
        out,
        groups,
        "FrameVOILUTSequence",
        (
            "WindowCenter",
            "WindowWidth",
            "WindowCenterWidthExplanation",
            "VOILUTFunction",
        ),
    )
    _copy_group_attrs(
        out,
        groups,
        "MREchoSequence",
        (("EffectiveEchoTime", "EchoTime"),),
    )
    _copy_group_attrs(
        out,
        groups,
        "MRTimingAndRelatedParametersSequence",
        (
            "RepetitionTime",
            "FlipAngle",
        ),
    )

    for group in groups:
        frame_content = _sequence_item(group, "FrameContentSequence", 0)
        if frame_content is None:
            continue
        if hasattr(frame_content, "InStackPositionNumber"):
            out.InstanceNumber = int(frame_content.InStackPositionNumber)
        if hasattr(frame_content, "FrameAcquisitionNumber"):
            out.AcquisitionNumber = int(frame_content.FrameAcquisitionNumber)
        if hasattr(frame_content, "FrameAcquisitionDateTime"):
            _set_acquisition_datetime(out, str(frame_content.FrameAcquisitionDateTime))

    for group in groups:
        frame_type = _sequence_item(group, "MRImageFrameTypeSequence", 0)
        if frame_type is None:
            continue
        if hasattr(frame_type, "FrameType"):
            out.ImageType = list(frame_type.FrameType)
        _copy_attrs(
            out,
            frame_type,
            (
                "PixelPresentation",
                "VolumetricProperties",
                "VolumeBasedCalculationTechnique",
                "ComplexImageComponent",
                "AcquisitionContrast",
            ),
        )


def _copy_group_attrs(
    out: Dataset,
    groups: Iterable[Dataset | None],
    sequence_keyword: str,
    attrs: Iterable[str | tuple[str, str]],
) -> None:
    for group in groups:
        item = _sequence_item(group, sequence_keyword, 0)
        if item is None:
            continue
        _copy_attrs(out, item, attrs)


def _copy_attrs(
    out: Dataset,
    source: Dataset,
    attrs: Iterable[str | tuple[str, str]],
) -> None:
    for attr in attrs:
        if isinstance(attr, tuple):
            source_attr, target_attr = attr
        else:
            source_attr = target_attr = attr
        if hasattr(source, source_attr):
            setattr(out, target_attr, copy.deepcopy(getattr(source, source_attr)))


def _set_acquisition_datetime(out: Dataset, value: str) -> None:
    if len(value) >= 8:
        out.AcquisitionDate = value[:8]
    if len(value) >= 14:
        out.AcquisitionTime = value[8:]


def _set_pixel_data(
    out: Dataset,
    pixel_array: np.ndarray,
    frame_index: int,
    frame_count: int,
) -> None:
    frame = _frame_at(pixel_array, frame_index, frame_count)
    if frame.ndim < 2:
        raise ConversionError(f"Frame {frame_index + 1} has invalid shape: {frame.shape}")

    frame = np.asarray(frame)
    if frame.dtype.byteorder == ">":
        frame = frame.byteswap().view(frame.dtype.newbyteorder("<"))
    frame = np.ascontiguousarray(frame)

    out.Rows = int(frame.shape[0])
    out.Columns = int(frame.shape[1])
    pixel_bytes = frame.tobytes()
    if len(pixel_bytes) % 2:
        pixel_bytes += b"\x00"
    out.PixelData = pixel_bytes


def _frame_at(pixel_array: np.ndarray, frame_index: int, frame_count: int) -> np.ndarray:
    array = np.asarray(pixel_array)
    if frame_count == 1:
        return array
    if array.ndim < 3 or array.shape[0] != frame_count:
        raise ConversionError(
            f"Expected pixel array with first dimension {frame_count}, got {array.shape}"
        )
    return array[frame_index]


def _set_slice_location(ds: Dataset) -> None:
    if not hasattr(ds, "ImageOrientationPatient") or not hasattr(ds, "ImagePositionPatient"):
        return

    try:
        orientation = np.asarray([float(x) for x in ds.ImageOrientationPatient], dtype=float)
        position = np.asarray([float(x) for x in ds.ImagePositionPatient], dtype=float)
        row = orientation[:3]
        column = orientation[3:]
        normal = np.cross(row, column)
        ds.SliceLocation = float(np.dot(position, normal))
    except Exception:
        return


def _iter_input_files(input_path: Path, *, recursive: bool) -> Iterable[Path]:
    if input_path.is_file():
        yield input_path
        return

    iterator = input_path.rglob("*") if recursive else input_path.iterdir()
    for path in sorted(iterator):
        if path.is_file():
            yield path


def _read_dicom_or_none(source: Path, *, force: bool) -> Dataset | None:
    try:
        return pydicom.dcmread(source, force=force)
    except (InvalidDicomError, IsADirectoryError, PermissionError):
        return None


def _copy_single_frame(source: Path, output_dir: Path, *, overwrite: bool) -> Path:
    target = output_dir / source.name
    if target.exists() and not overwrite:
        raise ConversionError(
            f"Output file already exists: {target}. Use --overwrite to replace it."
        )
    shutil.copy2(source, target)
    return target


def _sequence_item(ds: Dataset | None, keyword: str, index: int) -> Dataset | None:
    if ds is None or not hasattr(ds, keyword):
        return None
    sequence = getattr(ds, keyword)
    if not sequence or index >= len(sequence):
        return None
    return sequence[index]


def _delete_keyword(ds: Dataset, keyword: str) -> None:
    tag = tag_for_keyword(keyword)
    if tag is not None and tag in ds:
        del ds[tag]


def _frame_count(ds: Dataset) -> int:
    try:
        return int(ds.get("NumberOfFrames", 1))
    except (TypeError, ValueError):
        return 1


def _series_folder_name(source: Path) -> str:
    stem = source.stem or "converted"
    safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in stem)
    return safe[:80] or "converted"


def _truncate_long_string(value: str, max_length: int = 64) -> str:
    return value[:max_length]
