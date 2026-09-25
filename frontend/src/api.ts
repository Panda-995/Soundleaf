import type { ReactNode } from "react";

export type Segment = {
  text: string;
  voice: string;
  emotion: string;
  speed: number;
  pause: number;
  speaker: string;
};
export type Chapter = {
  id: string;
  title: string;
  position: number;
  revision: number;
  active_audio: string | null;
  audio_revision: number | null;
  duration: number;
  characters: number;
  voice_stale?: number;
  stale_count?: number;
};
export type BookStyle = {
  preset?: string;
  narration_speed?: number;
  dialogue_pause?: number;
  narration_pause?: number;
};
export type Book = {
  id: string;
  title: string;
  author: string;
  cover: string | null;
  voice: string;
  chapters: Chapter[];
  completed: number;
  style?: BookStyle | null;
  intro?: string | null;
};
/** Shape returned by /api/books (list): "chapters" is a COUNT there, while
 * /api/books/{id} returns the chapter array. Keeping them apart stops list
 * views from treating the count as an array. */
export type BookSummary = Omit<Book, "chapters"> & { chapters: number };
export type BookMeta = {
  author: string;
  intro: string;
  tags: string[];
  palette: string[];
  mood: string;
};
export type Voice = { id: string; name: string; description: string };
export type DictEntry = { word: string; replacement: string };
export type AudioMeta = {
  id: string;
  chapter_id: string;
  duration: number;
  peaks: number[];
  timeline: { index: number; start: number; end: number }[];
  quality?: { segments: { index: number; issues: string[] }[] };
};
export type ChapterDetail = Chapter & {
  book_id: string;
  source: string;
  segments: Segment[];
  suggestion: {
    revision: number;
    segments: {
      index: number;
      text: string;
      voice: string;
      speaker?: string;
      voice_hint?: string;
      emotion: string;
      speed: number;
      pause: number;
      reason: string;
    }[];
  } | null;
  restructure?: {
    segments: Segment[];
    existing_revision: number;
  } | null;
  versions: { id: string; revision: number; duration: number }[];
  marks: { id: string; note: string; seconds: number }[];
};


export async function api<T = any>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const form = body instanceof FormData;
  const response = await fetch("/api" + path, {
    method,
    credentials: "same-origin",
    headers: {
      "X-Soundleaf": "1",
      ...(!form && body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? (form ? body : JSON.stringify(body)) : undefined,
  });
  if (!response.ok) {
    let data;
    try {
      data = await response.json();
    } catch {
      data = { detail: "请求失败" };
    }
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : response.status === 422
          ? "请检查输入的内容、长度和数值范围"
          : "请求失败，请重试",
    );
  }
  return response.json();
}

export type ProviderConfig = {
  provider: string;
  base_url: string;
  model: string;
  voice: string;
  allow_local: boolean;
  has_key?: boolean;
  image_model?: string;
};
export type SettingsShape = {
  tts: ProviderConfig;
  ai: ProviderConfig;
  notify: { enabled: boolean; kind: string; url: string } | null;
  paused: boolean;
  favorites: string[];
  data_dir: string;
  free_bytes: number;
  total_bytes: number;
};

export type Common = {
  run: (fn: () => Promise<void>) => Promise<void>;
  notify: (s: string, assertive?: boolean) => void;
  go: (s: string) => void;
  reload: () => void;
  busy: boolean;
  book: Book | null;
  bookId: string;
  chapterId: string;
  setChapterId: (s: string) => void;
  voices: Voice[];
  settings: SettingsShape | null;
  setModal: (v: { title: string; content: ReactNode } | null) => void;
  playAudio: (
    id: string,
    label: string,
    bid?: string,
    start?: number,
  ) => Promise<void>;
  preview: (s: Segment) => Promise<void>;
  supportsEmotion: boolean;
  confirmGenerate: (ids: string[]) => void;
  setNavGuard: (guard: (() => boolean) | null) => void;
};
