import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from media_type import detected_media_type


@pytest.mark.parametrize('header,expected', [
    (b'\xff\xd8\xff\xe0', 'image/jpeg'),
    (b'\x89PNG\r\n\x1a\n', 'image/png'),
    (b'GIF89a', 'image/gif'),
    (b'RIFF1234WEBP', 'image/webp'),
    (b'\x00\x00\x00\x18ftypisom', 'video/mp4'),
    (b'%PDF-1.7', 'application/pdf'),
    (b'unknown', 'application/octet-stream'),
])
def test_generic_imported_files_are_classified_by_content(header, expected):
    assert detected_media_type(header, 'application/octet-stream') == expected


def test_preserve_known_type():
    assert detected_media_type(b'anything', 'video/webm') == 'video/webm'
