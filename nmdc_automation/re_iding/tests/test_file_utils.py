import pysam
import pytest
import os
from unittest import mock
from pathlib import Path

from nmdc_automation.re_iding.file_utils import (
    rewrite_bam,
    replace_and_write_bam,
    md5_sum,
    link_data_file_paths,
    get_corresponding_data_file_path_for_url,
)


def test_sample_bam(sample_bam):
    # Check if the sample BAM file exists
    assert os.path.exists(sample_bam)

    # Check if the sample BAM file is not empty
    assert os.path.getsize(sample_bam) > 0


def test_rewrite_bam(sample_bam, tmpdir):
    # Define input and output BAM file paths
    input_bam = sample_bam
    output_bam = str(tmpdir.join("output.bam"))

    # Define old and new patterns for modification
    old_pattern = "nmdc:mga0zv48"
    new_pattern = "nmdc:updated_id"

    # Call the modify_bam function
    rewrite_bam(input_bam, output_bam, old_pattern, new_pattern)

    # Check if the output BAM file exists
    assert os.path.exists(output_bam)

    # Check if the output BAM file is not empty
    assert os.path.getsize(output_bam) > 0

    # Check if the modification has been applied correctly
    with pysam.AlignmentFile(output_bam, "rb") as output_bam_file:
        for read in output_bam_file.fetch(until_eof=True):
            assert new_pattern in read.reference_name

    # Check if the MD5 checksum and file size are correct
    expected_md5 = md5_sum(output_bam)
    expected_size = os.path.getsize(output_bam)
    assert expected_md5, expected_size == rewrite_bam(input_bam, output_bam, old_pattern, new_pattern)

def test_replace_and_write_bam(sample_bam, tmpdir):
    # Define input and output BAM file paths
    input_bam = sample_bam
    output_bam = str(tmpdir.join("output.bam"))

    # Define old and new patterns for modification
    old_pattern = "nmdc:mga0zv48"
    new_pattern = "nmdc:updated_id"

    # Call the modify_bam function
    replace_and_write_bam(input_bam, output_bam, old_pattern, new_pattern)

    # Check if the output BAM file exists
    assert os.path.exists(output_bam)

    # Check if the output BAM file is not empty
    assert os.path.getsize(output_bam) > 0


def test_valid_link_creation(tmp_path):
    old_base_dir = tmp_path / "old_base"
    new_path = tmp_path / "new_link"
    old_base_dir.mkdir(parents=True)
    (old_base_dir / "path/to").mkdir(parents=True)
    old_file = old_base_dir / "path/to/file.txt"
    old_file.write_text("test content")

    old_url = "https://data.microbiomedata.org/data/path/to/file.txt"

    with mock.patch('os.link') as mock_link:
        link_data_file_paths(old_url, old_base_dir, new_path)
        mock_link.assert_called_once_with(old_file, new_path)

def test_existing_link(tmp_path):
    old_base_dir = tmp_path / "old_base"
    new_path = tmp_path / "new_link"
    old_base_dir.mkdir(parents=True)
    (old_base_dir / "path/to").mkdir(parents=True)
    old_file = old_base_dir / "path/to/file.txt"
    old_file.write_text("test content")
    new_path.write_text("test content")

    old_url = "https://data.microbiomedata.org/data/path/to/file.txt"

    with mock.patch('os.link') as mock_link:
        with mock.patch('logging.info') as mock_log_info:
            link_data_file_paths(old_url, old_base_dir, new_path)
            mock_link.assert_not_called()
            mock_log_info.assert_any_call(f"File already exists at {new_path}. Skipping linking.")

def test_invalid_url():
    old_base_dir = Path("/some/base/dir")
    new_path = Path("/some/new/path")
    old_url = "https://invalid.url/path/to/file.txt"

    with mock.patch('logging.error') as mock_log_error:
        link_data_file_paths(old_url, old_base_dir, new_path)
        mock_log_error.assert_any_call(f"The URL {old_url} does not start with the expected base URL https://data.microbiomedata.org/data/.")

def test_link_creation_error(tmp_path):
    old_base_dir = tmp_path / "old_base"
    new_path = tmp_path / "new_link"
    old_base_dir.mkdir(parents=True)
    (old_base_dir / "path/to").mkdir(parents=True)
    old_file = old_base_dir / "path/to/file.txt"
    old_file.write_text("test content")

    old_url = "https://data.microbiomedata.org/data/path/to/file.txt"

    with mock.patch('os.link', side_effect=OSError("link error")) as mock_link:
        with mock.patch('logging.error') as mock_log_error:
            link_data_file_paths(old_url, old_base_dir, new_path)
            mock_link.assert_called_once_with(old_file, new_path)
            mock_log_error.assert_any_call(f"An error occurred while linking the file from {old_file} to {new_path}: link error")

def test_unexpected_error(tmp_path):
    old_base_dir = tmp_path / "old_base"
    new_path = tmp_path / "new_link"
    old_base_dir.mkdir(parents=True)
    (old_base_dir / "path/to").mkdir(parents=True)
    old_file = old_base_dir / "path/to/file.txt"
    old_file.write_text("test content")

    old_url = "https://data.microbiomedata.org/data/path/to/file.txt"

    with mock.patch('os.link', side_effect=Exception("unexpected error")) as mock_link:
        with mock.patch('logging.error') as mock_log_error:
            link_data_file_paths(old_url, old_base_dir, new_path)
            mock_link.assert_called_once_with(old_file, new_path)
            mock_log_error.assert_any_call(f"Unexpected error while linking the file from {old_file} to {new_path}: unexpected error")

def test_get_corresponding_data_file_for_url(data_dir):
    file_path = data_dir / "nmdc:omprc-11-wmzpa354" / "nmdc:wfmgas-11-y43zyn66.1" / "nmdc_wfmgas-11-y43zyn66.1_contigs.fna"
    file_path.parent.mkdir(parents=True)
    file_path.touch()

    url = "https://data.microbiomedata.org/data/nmdc:omprc-11-wmzpa354/nmdc:wfmgas-11-y43zyn66.1/nmdc_wfmgas-11-y43zyn66.1_contigs.fna"
    result = get_corresponding_data_file_path_for_url(url, data_dir)
    assert result == file_path

def test_get_corresponding_data_file_for_url_nearest_match(data_dir):
    file_path = data_dir / "nmdc:omprc-11-wmzpa354" / "nmdc:wfmgas-11-y43zyn66.1" / "nmdc_wfmgas-11-y43zyn66.1.1_contigs.fna"
    file_path.parent.mkdir(parents=True)
    file_path.touch()

    url = "https://data.microbiomedata.org/data/nmdc:omprc-11-wmzpa354/nmdc:wfmgas-11-y43zyn66.1/nmdc_wfmgas-11-y43zyn66.1_contigs.fna"
    result = get_corresponding_data_file_path_for_url(url, data_dir)
    assert result == file_path

def test_get_corresponding_data_file_for_url_invalid_url(data_dir):
    url = "https://data.microbiomedata.org/data/nmdc:omprc-11-wmzpa354/nmdc:wfmgas-11-y43zyn66.1/nmdc_wfmgas-11-y43zyn66.1_contigs.fna"
    result = get_corresponding_data_file_path_for_url(url, data_dir)
    assert result is None

def test_get_corresponding_data_file_for_url_multiple_files_raises_exception(data_dir):
    file_path = data_dir / "nmdc:omprc-11-wmzpa354" / "nmdc:wfmgas-11-y43zyn66.1" / "nmdc_wfmgas-11-y43zyn66.1.1.1_contigs.fna"
    file_path.parent.mkdir(parents=True)
    file_path.touch()
    file_path_2 = data_dir / "nmdc:omprc-11-wmzpa354" / "nmdc:wfmgas-11-y43zyn66.1" / "nmdc_wfmgas-11-y43zyn66.1.1_contigs.fna"
    file_path_2.touch()

    url = "https://data.microbiomedata.org/data/nmdc:omprc-11-wmzpa354/nmdc:wfmgas-11-y43zyn66.1/nmdc_wfmgas-11-y43zyn66.1_contigs.fna"
    with pytest.raises(ValueError) as e:
        get_corresponding_data_file_path_for_url(url, data_dir)