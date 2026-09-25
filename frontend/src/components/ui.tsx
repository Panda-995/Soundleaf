import { type ReactNode } from "react";
import {
  AudioLines,
} from "lucide-react";
import { t } from "../i18n";

export function Button({
  children,
  onClick,
  primary = false,
  disabled = false,
  className = "",
  type = "button",
  title,
}: {
  children: ReactNode;
  onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void;
  primary?: boolean;
  disabled?: boolean;
  className?: string;
  type?: "button" | "submit";
  title?: string;
}) {
  return (
    <button
      type={type}
      title={title}
      aria-label={title}
      disabled={disabled}
      className={`button ${primary ? "primary" : ""} ${className}`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
export function Cover({
  book,
  large = false,
}: {
  book: { title: string; cover?: string | null; id?: string };
  large?: boolean;
}) {
  return (
    <div className={`cover ${large ? "large" : ""}`}>
      {book.cover ? (
        <img src={`/api/books/${book.id}/cover`} alt={`${book.title}封面`} />
      ) : (
        <>
          <div className="cover-horizon" />
          <div className="lighthouse">
            <i />
          </div>
          <div className="cover-title">{book.title}</div>
          <small>声页 · 有声书</small>
        </>
      )}
    </div>
  );
}
export function Badge({
  children,
  kind = "",
  live = false,
}: {
  children: ReactNode;
  kind?: string;
  /** Pulsing dot for genuinely live states (a job that is running now). */
  live?: boolean;
}) {
  return <span className={"badge " + kind + (live ? " live" : "")}>{children}</span>;
}
export function Logo({
  size = 38,
  showText = true,
}: {
  size?: number;
  showText?: boolean;
}) {
  // Two glyphs that say "声音 + 页": a source dot above three audio bars of
  // varying height. No frame, no fill, single brand color. A standalone mark,
  // not an illustration.
  return (
    <div className="brand-logo" aria-label={t("声页 Logo")}>
      <svg
        viewBox="0 0 64 64"
        width={size}
        height={size}
        aria-hidden="true"
      >
        <circle cx="32" cy="12" r="3" fill="var(--lime)" />
        <g
          stroke="var(--lime)"
          strokeWidth="3.6"
          strokeLinecap="round"
          fill="none"
        >
          <line x1="18" y1="26" x2="18" y2="38" />
          <line x1="32" y1="22" x2="32" y2="42" />
          <line x1="46" y1="26" x2="46" y2="38" />
        </g>
      </svg>
      {showText && (
        <span className="brand-logo-text">
          声页<span className="dot">.</span>
        </span>
      )}
    </div>
  );
}
export function Heading({
  title,
  sub,
  children,
}: {
  title: string;
  sub?: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      <div className="actions">{children}</div>
    </div>
  );
}
export function Empty({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-symbol">
        <AudioLines size={48} />
      </div>
      <h2>{title}</h2>
      <p>{description}</p>
      <div className="actions">{children}</div>
    </div>
  );
}
// Long chapters would render one DOM node per ~7.5ms of audio (133/s); fixed
// bucket downsampling keeps the waveform at a few hundred bars regardless.
const WAVE_BARS = 600;
function downsample(peaks: number[], bars = WAVE_BARS): number[] {
  if (peaks.length <= bars) return peaks;
  const out: number[] = [];
  const bucket = peaks.length / bars;
  for (let i = 0; i < bars; i++) {
    let value = 0;
    const from = Math.floor(i * bucket);
    const to = Math.min(peaks.length, Math.floor((i + 1) * bucket) + 1);
    for (let j = from; j < to; j++) value = Math.max(value, peaks[j]);
    out.push(value);
  }
  return out;
}
export function Wave({
  peaks = [],
  position = 0,
  onSeek,
}: {
  peaks?: number[];
  position?: number;
  onSeek?: (v: number) => void;
}) {
  return (
    <div
      className="wave"
      role={onSeek ? "slider" : undefined}
      tabIndex={onSeek ? 0 : undefined}
      aria-label={t("音频波形进度")}
      aria-valuenow={onSeek ? Math.round(position * 100) : undefined}
      aria-valuemin={onSeek ? 0 : undefined}
      aria-valuemax={onSeek ? 100 : undefined}
      onClick={(e) => {
        if (onSeek) {
          const r = e.currentTarget.getBoundingClientRect();
          onSeek((e.clientX - r.left) / r.width);
        }
      }}
      onKeyDown={(e) => {
        if (onSeek && ["ArrowLeft", "ArrowRight"].includes(e.key)) {
          e.preventDefault();
          onSeek(
            Math.max(
              0,
              Math.min(1, position + (e.key === "ArrowRight" ? 0.02 : -0.02)),
            ),
          );
        }
      }}
    >
      {peaks.length ? (
        downsample(peaks).map((p, i, bars) => (
          <i
            key={i}
            className={i / bars.length < position ? "heard" : ""}
            style={{ height: `${Math.max(3, p * 100)}%` }}
          />
        ))
      ) : (
        <span className="wave-placeholder">{t("生成音频后显示波形")}</span>
      )}
    </div>
  );
}
