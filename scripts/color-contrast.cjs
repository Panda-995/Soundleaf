// Opaque CSS colors used by the design tokens, converted to linear sRGB.
function parseLinearRgb(color) {
  const number = '([+-]?(?:\\d*\\.)?\\d+(?:e[+-]?\\d+)?)';
  const oklch = String(color).match(new RegExp(`^oklch\\(\\s*${number}\\s+${number}\\s+${number}(?:deg)?\\s*\\)$`, 'i'));
  const clamp = value => Math.min(1, Math.max(0, value));
  if (oklch) {
    const L = +oklch[1], C = +oklch[2], hue = +oklch[3] * Math.PI / 180;
    const a = C * Math.cos(hue), b = C * Math.sin(hue);
    const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
    const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
    const s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3;
    return [
      4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
      -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
      -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    ].map(clamp);
  }
  const rgb = String(color).match(new RegExp(`^rgb\\(\\s*${number}\\s*,\\s*${number}\\s*,\\s*${number}\\s*\\)$`, 'i'));
  if (!rgb) return null;
  return rgb.slice(1).map(value => {
    const channel = clamp(+value / 255);
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  });
}

function contrast(foreground, background) {
  const luminance = color => {
    const rgb = parseLinearRgb(color);
    return rgb && (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]);
  };
  const a = luminance(foreground), b = luminance(background);
  return a === null || b === null ? null : (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

module.exports = { parseLinearRgb, contrast };
