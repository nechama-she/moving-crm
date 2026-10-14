export async function normalizeLiveSwitchVideo(content: Blob): Promise<Blob> {
  const type = content.type.toLowerCase().split(';')[0].trim();
  if (content.size && type.startsWith('video/')) return content;
  if (content.size && ['', 'application/octet-stream', 'binary/octet-stream'].includes(type)) {
    const header = new Uint8Array(await content.slice(0, 32).arrayBuffer());
    const tag = (start: number, end: number) => String.fromCharCode(...header.slice(start, end));
    // MP4/QuickTime containers declare their format in the first file-type box.
    if (header.length >= 16 && tag(4, 8) === 'ftyp') {
      const brand = tag(8, 12);
      if (/^(isom|iso[2-9]|mp4[12]|avc1|dash|M4V |MSNV|qt  )$/.test(brand)) {
        return content.slice(0, content.size, brand === 'qt  ' ? 'video/quicktime' : 'video/mp4');
      }
    }
  }
  throw new Error(`LiveSwitch returned ${content.type || 'an unknown file type'}, not a downloadable video.`);
}
