import {
  BookOpen,
  Upload,
  ListMusic,
  Clapperboard,
  Users,
  AudioLines,
  ListTodo,
  Headphones,
  Download,
  Settings,
} from "lucide-react";
import type { Segment, ChapterDetail } from "./api";
import { t, tf } from "./i18n";

export const navItems = [
  ["library", "书架", BookOpen],
  ["import", "导入小说", Upload],
  ["chapters", "章节工作台", ListMusic],
  ["cast", "角色库", Users],
  ["director", "AI 导演", Clapperboard],
  ["voices", "音色库", AudioLines],
  ["queue", "任务队列", ListTodo],
  ["listen", "试听", Headphones],
  ["export", "导出", Download],
  ["settings", "设置", Settings],
] as const;
export const emotions: Record<string, string> = {
  neutral: "默认",
  calm: "平静",
  happy: "喜悦",
  sad: "悲伤",
  angry: "愤怒",
  fearful: "恐惧",
  disgusted: "厌恶",
  surprised: "惊讶",
  excited: "激动",
  laughing: "笑意",
  gentle: "温柔",
  charming: "妩媚",
  breathy: "娇喘",
  whisper: "耳语",
  solemn: "沉重",
  sobbing: "哭腔",
  anxious: "不安",
  confused: "疑惑",
  sarcastic: "嘲讽",
  indifferent: "冷漠",
  stutter: "结巴",
};
export const statusText: Record<string, string> = {
  queued: "等待中",
  running: "处理中",
  succeeded: "已完成",
  failed: "失败",
  needs_review: "结果待确认",
  cancelled: "已取消",
};
export const formatTime = (n = 0) =>
  `${Math.floor(n / 60)
    .toString()
    .padStart(2, "0")}:${Math.floor(n % 60)
    .toString()
    .padStart(2, "0")}`;
// 中文朗读的平均语速（字/秒），只用于生成前的粗略时长预估。
export const CHARS_PER_SECOND = 4.2;
export function estimateDuration(chars: number): string {
  if (!chars) return "";
  const minutes = Math.max(1, Math.round(chars / CHARS_PER_SECOND / 60));
  return minutes < 60
    ? tf("约 {minutes} 分钟", { minutes })
    : tf("约 {hours} 小时 {minutes} 分钟", { hours: Math.floor(minutes / 60), minutes: minutes % 60 });
}
/** Timeline entry covering a playback position (for mark → segment jumps). */
export function segmentIndexAt(
  timeline: { index: number; start: number; end: number }[],
  seconds: number,
): number | null {
  return (
    timeline.find((t) => seconds >= t.start && seconds < t.end)?.index ?? null
  );
}
export const baseSegment = (text: string): Segment => ({
  text,
  voice: "",
  emotion: "neutral",
  speed: 1,
  pause: 250,
  speaker: "旁白",
});
export function collectSpeakers(detail: ChapterDetail) {
  const map = new Map<
    string,
    { name: string; hint: string; count: number; voice: string }
  >();
  for (let i = 0; i < detail.segments.length; i++) {
    const seg = detail.segments[i];
    const name = seg.speaker || "旁白";
    const sug = detail.suggestion?.segments.find((v) => v.index === i);
    const existing = map.get(name) || {
      name,
      hint: "",
      count: 0,
      voice: seg.voice || "",
    };
    existing.count += 1;
    if (!existing.voice && seg.voice) existing.voice = seg.voice;
    if (sug?.voice_hint && !existing.hint) existing.hint = sug.voice_hint;
    map.set(name, existing);
  }
  return Array.from(map.values());
}

export const qualityLabels: Record<string, string> = {
  silent: "疑似静音",
  too_short: "时长异常",
  clipping: "疑似爆音",
};

export const APP_VERSION = "v1.1.0";
