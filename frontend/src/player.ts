import { useEffect, useRef, useState } from "react";
import { api, type AudioMeta } from "./api";

type PlayerOptions = {
  notify: (message: string) => void;
  run: (fn: () => Promise<void>) => Promise<void>;
  bookId: string;
  chapters: { id: string; title: string; active_audio: string | null }[];
};

/** Player state, synthesis preview polling and progress persistence in one
 * place. Options are read through a ref, so callers may pass inline values. */
export function usePlayer(options: PlayerOptions) {
  const latest = useRef(options);
  latest.current = options;

  const [audioMeta, setAudioMeta] = useState<AudioMeta | null>(null);
  const [audioLabel, setAudioLabel] = useState("选择一段声音，开始试听");
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [rate, setRate] = useState(1);
  const [volume, setVolume] = useState(0.8);
  const audioRef = useRef<HTMLAudioElement>(null);
  const playBook = useRef("");
  const lastProgress = useRef(0);
  const pendingSeek = useRef(0);
  const playSeq = useRef(0);
  const metaRef = useRef<AudioMeta | null>(null);
  metaRef.current = audioMeta;

  useEffect(() => {
    if (!audioMeta || !audioRef.current) return;
    const a = audioRef.current;
    a.load();
    a.play().catch(() => latest.current.notify("音频已载入，请点击播放。"));
  }, [audioMeta?.id]);
  useEffect(() => {
    if (audioRef.current) {
      audioRef.current.playbackRate = rate;
      audioRef.current.volume = volume;
    }
  }, [rate, volume]);

  async function playAudio(
    id: string,
    label: string,
    bid = latest.current.bookId,
    start = 0,
  ) {
    // Guard against rapid chapter switches: only the newest request may
    // touch the player or the saved position.
    const seq = ++playSeq.current;
    const meta = await api<AudioMeta>("/audio/" + id + "/metadata");
    if (seq !== playSeq.current) return;
    pendingSeek.current = Math.max(
      0,
      Math.min(start, Math.max(0, meta.duration - 0.1)),
    );
    playBook.current = bid;
    setAudioLabel(label);
    setPosition(pendingSeek.current);
    if (metaRef.current?.id === id && audioRef.current) {
      audioRef.current.currentTime = pendingSeek.current;
      await audioRef.current.play();
    } else setAudioMeta(meta);
  }
  function togglePlay() {
    const a = audioRef.current;
    if (!metaRef.current || !a) return;
    if (a.paused) a.play().catch(() => latest.current.notify("无法播放音频"));
    else a.pause();
  }
  function seek(v: number) {
    const meta = metaRef.current;
    if (audioRef.current && meta)
      audioRef.current.currentTime = Math.max(0, Math.min(meta.duration, v));
  }
  function updateTime() {
    const a = audioRef.current;
    if (!a) return;
    setPosition(a.currentTime);
    const meta = metaRef.current;
    if (
      playBook.current &&
      meta &&
      Date.now() - lastProgress.current > 5000
    ) {
      lastProgress.current = Date.now();
      api(`/books/${playBook.current}/progress`, "PUT", {
        audio_id: meta.id,
        seconds: a.currentTime,
      }).catch(() => {});
    }
  }
  function nextChapter() {
    const chapters = latest.current.chapters || [];
    const meta = metaRef.current;
    if (!chapters.length || !meta) return;
    const index = chapters.findIndex((c) => c.id === meta.chapter_id);
    const next = chapters.slice(index + 1).find((c) => c.active_audio);
    if (index >= 0 && next)
      latest.current.run(() => playAudio(next.active_audio!, next.title));
  }
  function reset() {
    audioRef.current?.pause();
    setAudioMeta(null);
    setPosition(0);
    setAudioLabel("选择一段声音，开始试听");
    playBook.current = "";
  }
  /** Spread onto the single <audio> element. */
  function audioProps(srcId: string | undefined) {
    return {
      ref: audioRef,
      src: srcId ? `/api/audio/${srcId}` : undefined,
      onLoadedMetadata: () => {
        if (audioRef.current) {
          audioRef.current.currentTime = pendingSeek.current;
          audioRef.current.playbackRate = rate;
          audioRef.current.volume = volume;
        }
      },
      onTimeUpdate: updateTime,
      onPlay: () => setPlaying(true),
      onPause: () => setPlaying(false),
      onEnded: nextChapter,
      onError: () =>
        metaRef.current &&
        latest.current.notify("音频加载失败，请检查文件是否存在"),
    };
  }
  return {
    audioMeta,
    audioLabel,
    playing,
    position,
    rate,
    setRate,
    volume,
    setVolume,
    playAudio,
    togglePlay,
    seek,
    reset,
    audioProps,
  };
}
export type Player = ReturnType<typeof usePlayer>;
