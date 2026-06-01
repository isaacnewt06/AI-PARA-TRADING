from src.processing.archive_groups import multipart_status, parse_archive_part


def test_parse_archive_part_detects_group() -> None:
    info = parse_archive_part("MES_3.part2.rar")

    assert info.is_multipart is True
    assert info.group_key == "MES_3"
    assert info.part_number == 2


def test_multipart_status_detects_complete_observed() -> None:
    total, status = multipart_status({1, 2, 3})

    assert total == 3
    assert status == "multipart_complete_observed"
