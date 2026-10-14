# Text encoding and UI changes

- Save source files as UTF-8. Use apply_patch for edits containing non-ASCII text.
- Never pipe literal non-ASCII source through PowerShell into Python or another process. Shell encoding can silently replace characters with question marks before the file is written, even with encoding="utf-8".
- If scripting an edit through a shell, keep the script ASCII-only and use Unicode escapes or HTML entities for special characters.
- Use SVG for UI icons rather than decorative Unicode characters.
- Inspect changed labels; passing compilation alone does not verify text or visual appearance.
