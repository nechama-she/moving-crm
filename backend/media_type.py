"""Identify common media stored with generic content types."""
def detected_media_type(header, current):
    current = (current or '').split(';')[0].strip().lower()
    if current not in ('', 'application/octet-stream', 'binary/octet-stream'):
        return current
    if header.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if header.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif'
    if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        return 'image/webp'
    if len(header) >= 12 and header[4:8] == b'ftyp':
        brand = header[8:12]
        if brand in (b'heic', b'heix', b'hevc', b'hevx'):
            return 'image/heic'
        if brand in (b'avif', b'avis'):
            return 'image/avif'
        if brand == b'qt  ':
            return 'video/quicktime'
        if brand in (b'isom', b'iso2', b'mp41', b'mp42', b'avc1', b'M4V ', b'dash'):
            return 'video/mp4'
    if header.startswith(b'%PDF-'):
        return 'application/pdf'
    return current or 'application/octet-stream'
