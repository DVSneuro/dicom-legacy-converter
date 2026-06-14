from __future__ import annotations

from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from dicom_legacy_converter.convert import (
    ENHANCED_MR_IMAGE_STORAGE,
    MR_IMAGE_STORAGE,
    convert_path,
    is_enhanced_mr,
    split_enhanced_mr_file,
)


def test_split_enhanced_mr_file_writes_classic_single_frame_instances(tmp_path: Path) -> None:
    source = tmp_path / "enhanced.dcm"
    _write_synthetic_enhanced_mr(source, frame_count=3)

    output_files = split_enhanced_mr_file(source, tmp_path / "out")

    assert len(output_files) == 3

    first = pydicom.dcmread(output_files[0])
    second = pydicom.dcmread(output_files[1])

    assert first.SOPClassUID == MR_IMAGE_STORAGE
    assert first.file_meta.MediaStorageSOPClassUID == MR_IMAGE_STORAGE
    assert first.file_meta.TransferSyntaxUID == ExplicitVRLittleEndian
    assert not hasattr(first, "NumberOfFrames")
    assert not hasattr(first, "PerFrameFunctionalGroupsSequence")
    assert first.SeriesInstanceUID == second.SeriesInstanceUID
    assert first.SOPInstanceUID != second.SOPInstanceUID
    assert first.InstanceNumber == 1
    assert second.InstanceNumber == 2
    assert [float(x) for x in second.ImagePositionPatient] == [0.0, 0.0, 2.5]
    assert second.SliceLocation == 2.5
    assert first.pixel_array.shape == (2, 2)
    assert np.array_equal(first.pixel_array, np.array([[0, 1], [2, 3]], dtype=np.uint16))


def test_is_enhanced_mr_accepts_sop_class(tmp_path: Path) -> None:
    source = tmp_path / "enhanced.dcm"
    _write_synthetic_enhanced_mr(source, frame_count=2)
    ds = pydicom.dcmread(source)

    assert is_enhanced_mr(ds)


def test_progress_callback_reports_sources_and_frames(tmp_path: Path) -> None:
    source = tmp_path / "enhanced.dcm"
    _write_synthetic_enhanced_mr(source, frame_count=10)
    messages: list[str] = []

    convert_path(
        source,
        tmp_path / "out",
        progress=messages.append,
        progress_interval=10,
    )

    assert "Found 1 source file(s)." in messages
    assert "source files: 0% (0/1)" in messages
    assert "source files: 100% (1/1)" in messages
    assert "enhanced.dcm: decoding pixel data (10 frame(s))." in messages
    assert "enhanced.dcm frames: 0% (0/10)" in messages
    assert "enhanced.dcm frames: 10% (1/10)" in messages
    assert "enhanced.dcm frames: 100% (10/10)" in messages


def test_skip_bold_uses_series_metadata(tmp_path: Path) -> None:
    source = tmp_path / "enhanced.dcm"
    _write_synthetic_enhanced_mr(
        source,
        frame_count=4,
        series_description="resting state BOLD",
        protocol_name="rfMRI_REST",
    )

    results = convert_path(source, tmp_path / "out", skip_bold=True)

    assert len(results) == 1
    assert not results[0].converted
    assert results[0].message == "skipped likely BOLD/fMRI series"
    assert not (tmp_path / "out").exists()


def test_max_series_frames_skips_combined_original_series(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    series_uid = generate_uid()
    _write_synthetic_enhanced_mr(
        input_dir / "enhanced_a.dcm",
        frame_count=6,
        series_uid=series_uid,
    )
    _write_synthetic_enhanced_mr(
        input_dir / "enhanced_b.dcm",
        frame_count=6,
        series_uid=series_uid,
    )

    results = convert_path(input_dir, tmp_path / "out", max_series_frames=10)

    assert len(results) == 2
    assert all(not result.converted for result in results)
    assert all("skipped series with 12 output frame(s)" in result.message for result in results)
    assert not (tmp_path / "out").exists()


def _write_synthetic_enhanced_mr(
    path: Path,
    *,
    frame_count: int,
    series_uid: str | None = None,
    series_description: str = "Synthetic T1",
    protocol_name: str | None = None,
) -> None:
    pixels = np.arange(frame_count * 2 * 2, dtype=np.uint16).reshape(frame_count, 2, 2)

    file_meta = FileMetaDataset()
    file_meta.FileMetaInformationVersion = b"\x00\x01"
    file_meta.MediaStorageSOPClassUID = ENHANCED_MR_IMAGE_STORAGE
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()

    ds = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    ds.SOPClassUID = ENHANCED_MR_IMAGE_STORAGE
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = series_uid or generate_uid()
    ds.PatientName = "Test^Enhanced"
    ds.PatientID = "TEST001"
    ds.Modality = "MR"
    ds.StudyDate = "20260613"
    ds.StudyTime = "120000"
    ds.SeriesDescription = series_description
    if protocol_name is not None:
        ds.ProtocolName = protocol_name
    ds.NumberOfFrames = frame_count
    ds.Rows = 2
    ds.Columns = 2
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.PixelData = pixels.tobytes()

    shared = Dataset()
    pixel_measures = Dataset()
    pixel_measures.PixelSpacing = ["1.0", "1.0"]
    pixel_measures.SliceThickness = "2.5"
    pixel_measures.SpacingBetweenSlices = "2.5"
    shared.PixelMeasuresSequence = Sequence([pixel_measures])

    orientation = Dataset()
    orientation.ImageOrientationPatient = ["1", "0", "0", "0", "1", "0"]
    shared.PlaneOrientationSequence = Sequence([orientation])

    transform = Dataset()
    transform.RescaleIntercept = "0"
    transform.RescaleSlope = "1"
    transform.RescaleType = "US"
    shared.PixelValueTransformationSequence = Sequence([transform])

    ds.SharedFunctionalGroupsSequence = Sequence([shared])

    per_frames = []
    for index in range(frame_count):
        group = Dataset()

        position = Dataset()
        position.ImagePositionPatient = ["0", "0", str(index * 2.5)]
        group.PlanePositionSequence = Sequence([position])

        frame_content = Dataset()
        frame_content.InStackPositionNumber = index + 1
        frame_content.FrameAcquisitionNumber = 1
        group.FrameContentSequence = Sequence([frame_content])

        frame_type = Dataset()
        frame_type.FrameType = ["ORIGINAL", "PRIMARY", "M", "NONE"]
        frame_type.PixelPresentation = "MONOCHROME"
        frame_type.VolumetricProperties = "VOLUME"
        frame_type.VolumeBasedCalculationTechnique = "NONE"
        frame_type.ComplexImageComponent = "MAGNITUDE"
        frame_type.AcquisitionContrast = "T1"
        group.MRImageFrameTypeSequence = Sequence([frame_type])

        per_frames.append(group)

    ds.PerFrameFunctionalGroupsSequence = Sequence(per_frames)
    ds.save_as(path, enforce_file_format=True)
