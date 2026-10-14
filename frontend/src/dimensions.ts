/** Parse feet, inches, or mixed dimensions; bare numbers are feet. */
export function dimensionFeet(input: string): number | null {
  const value = input.trim().toLowerCase().replace(/[\u2032\u2018\u2019]/g, "'").replace(/[\u2033\u201c\u201d]/g, '"');
  const n = '(\\d+(?:\\.\\d+)?|\\.\\d+)';
  const feet = "(?:'|ft|feet|foot)";
  const inches = '(?:"|in|inch|inches)';
  const mixed = value.match(new RegExp(`^${n}\\s*${feet}(?:\\s*${n}\\s*${inches})?$`));
  const onlyInches = value.match(new RegExp(`^${n}\\s*${inches}$`));
  const bare = value.match(new RegExp(`^${n}$`));
  const result = mixed ? Number(mixed[1]) + Number(mixed[2] || 0) / 12 : onlyInches ? Number(onlyInches[1]) / 12 : bare ? Number(bare[1]) : NaN;
  return Number.isFinite(result) && result > 0 ? result : null;
}
