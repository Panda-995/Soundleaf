// Dictionary for Director.tsx and Listen.tsx (group B).
// Keys are the exact zh source strings; t()/tf() fall back to the key itself.
const dict: Record<string, string> = {
  // Director — heading, chapter nav, script header
  "正在打开章节": "Opening chapter",
  "{book} / 朗读脚本 · 版本 {revision}": "{book} / Narration script · revision {revision}",
  "重新载入": "Reload",
  "保存": "Save",
  "生成本章": "Generate chapter",
  "有尚未保存的调整。保存后再生成；切换章节前请先保存。":
    "You have unsaved edits. Save before generating, and before switching chapters.",
  "有尚未保存的调整，离开将丢失这些修改。确定要离开吗？":
    "You have unsaved edits — leaving now loses them. Leave anyway?",
  "有尚未保存的调整，重新载入将丢弃这些修改。确定继续吗？":
    "You have unsaved edits — reloading discards them. Continue?",
  "工作区视图": "Workspace views",
  "章节列表": "Chapters",
  "朗读脚本": "Narration script",
  "划选正文词语可修正读音": "Select a word in the text to fix its pronunciation",

  // Director — analyze / restructure
  "AI 正在按语义重新切分段落，完成后可在下方预览。":
    "AI is re-splitting paragraphs by meaning; a preview will appear below when done.",
  "优化中…": "Re-segmenting…",
  "AI 优化分段": "AI re-segment",
  "正在分析本章段落与对话，完成后将在此显示建议。":
    "Analyzing this chapter's paragraphs and dialogue; suggestions will appear here when done.",
  "分析角色与对白…": "Analyzing characters & dialogue…",
  "AI 分析本章": "AI analyze chapter",
  "AI 正在按语义重新切分段落，原文不会改动。":
    "AI is re-splitting paragraphs by meaning; the original text is untouched.",
  "AI 正在逐段分析说话者、音色、语速与停顿，可在右侧查看。":
    "AI is analyzing speaker, voice, speed and pauses segment by segment; see the panel on the right.",

  // Director — restructure preview
  "AI 建议的分段": "AI-suggested segmentation",
  "已按对白/叙述细分并标注每个单元的说话者，原文逐字符未改动；采纳后 AI 分析可精确到每个角色的每句话。":
    "Split into dialogue/narration with a speaker tagged on each unit; the original text is unchanged character for character. Adopt it and AI analysis can pinpoint every line of every character.",
  "（空段）": "(empty segment)",
  "仅显示前 80 段，共 {total} 段。": "Showing the first 80 of {total} segments.",
  "已按 AI 建议重新分段。": "Segments replaced with the AI suggestion.",
  "采纳 AI 分段并替换现有脚本": "Adopt AI segmentation and replace the script",
  "已忽略本次 AI 分段建议。": "AI segmentation suggestion dismissed.",
  "忽略本次建议": "Dismiss this suggestion",

  // Director — script rows
  "章节标题": "Chapter title",
  "旁白": "Narrator",
  "AI 音色建议：{hint}": "AI voice suggestion: {hint}",
  "空片段": "Empty segment",
  "本章没有正文": "No text in this chapter",
  "添加文字后即可制作。": "Add some text to get started.",
  "添加正文": "Add text",
  "查看导入原文": "View imported source",

  // Director — inspector
  "朗读设置": "Narration settings",
  "片段 {n}": "Segment {n}",
  "朗读文本": "Narration text",
  "AI 任务处理中，暂时不能编辑": "AI task in progress; editing is temporarily unavailable",
  "说话者": "Speaker",
  "旁白、角色名或描述": "Narrator, character name, or description",
  "音色": "Voice",
  "片段音色": "Segment voice",
  "跟随书籍设置": "Follow book settings",
  "情绪": "Emotion",
  "片段情绪": "Segment emotion",
  "兼容接口不支持情绪参数，仅保留该项的语速与音量倾向。":
    "The compatibility API does not support emotion parameters; only its speed and volume tendencies are kept.",
  "合成语速": "Synthesis speed",
  "句尾停顿（毫秒）": "Sentence-end pause (ms)",
  "试听前 300 字": "Preview first 300 characters",
  "请先保存修改，再重生成音频": "Save your edits before regenerating audio",
  "正在重生成…": "Regenerating…",
  "重生成此段音频": "Regenerate this segment's audio",
  "只重新合成这一段并就地拼接，几秒完成；改动文本后需先保存。":
    "Re-synthesizes only this segment and splices it in place, done in seconds; save text edits first.",

  // Director — AI suggestion panel
  "AI 角色与朗读方案": "AI cast & narration plan",
  "已识别 {n} 个段落或对白。采纳后可逐段修改音色，再保存生成。":
    "Identified {n} segments or dialogue lines. Adopt to adjust each segment's voice, then save and generate.",
  "音色待指定": "Voice unassigned",
  "语速 {speed}×": "Speed {speed}×",
  "停顿 {pause}ms": "Pause {pause}ms",
  "音色建议：{hint}": "Voice suggestion: {hint}",
  "采纳角色、音色与朗读建议": "Adopt cast, voice and narration suggestions",
  "采纳后会替换当前片段；旧音频仍可试听。":
    "Adopting replaces the current segments; existing audio stays playable.",

  // Director — speaker map, versions
  "角色音色": "Character voices",
  "本章统一调整": "Adjust chapter-wide",
  "{count} 段": "{count} segments",
  "为{speaker}选择音色": "Choose a voice for {speaker}",
  "在此一键为某个角色统一指定音色；切换后需重新合成音频。":
    "Assign one voice to a character across the chapter; audio needs re-synthesis after switching.",
  "音频版本": "Audio versions",
  "版本 {revision} · {duration}": "Revision {revision} · {duration}",
  "试听版本{revision}": "Preview revision {revision}",

  // Director — poller / save notifications
  "片段重生成仍在处理，可从任务队列继续查看。":
    "Segment regeneration is still processing; check the job queue.",
  "该片段音频已就地更新。": "This segment's audio has been updated in place.",
  "片段重生成未完成": "Segment regeneration did not finish",
  "分析已取消": "Analysis cancelled",
  "角色与朗读建议已就绪，请核对后采纳。":
    "Cast and narration suggestions are ready; review and adopt them.",
  "优化分段已取消": "Re-segmentation cancelled",
  "AI 已重新切分章节，可在下方面板预览后再决定是否采纳。":
    "AI has re-split the chapter; preview it in the panel below before deciding whether to adopt.",
  "已保存。旧音频保留，可重新生成更新版本。":
    "Saved. Existing audio is kept; regenerate to produce a new version.",

  // Listen — heading and sidebar
  "听见故事": "Hear the story",
  "听一章，修一段，让声音慢慢成形。":
    "Listen to a chapter, mark a line, and let the voice slowly take shape.",
  "继续上次播放": "Resume last playback",
  "返回导演": "Back to Director",
  "我的有声书": "My audiobook",
  "未生成": "Not generated",
  "选择已生成的章节": "Select a generated chapter",

  // Listen — playback controls
  "后退15秒": "Back 15 seconds",
  "暂停": "Pause",
  "播放": "Play",
  "前进15秒": "Forward 15 seconds",

  // Listen — marks
  "标记试听问题": "Mark a listening issue",
  "问题已标记，可在章节中检查。": "Marked. You can review it in the chapter text.",
  "问题说明": "Issue description",
  "例如：人名读音不正确": "e.g. a character's name is mispronounced",
  "保存标记": "Save mark",
  "标记问题": "Mark issue",
  "下载本章": "Download chapter",
  "试听标记": "Listening marks",
  "跳转到导演页的这个片段": "Jump to this segment in the Director",
  "去修复": "Go fix",

  // Listen — now playing / reading text
  "当前位置在片段之间": "Currently between segments",
  "书籍默认音色": "Book default voice",
  "巡检发现 {n} 段疑似异常（静音 / 时长异常 / 爆音），已用标记标出。":
    "The scan found {n} segments with possible issues (silence / abnormal length / clipping), flagged below.",
  "跳转到第 {index} 段，存在质量标记": "Jump to segment {index}; has quality marks",
  "跳转到第 {index} 段": "Jump to segment {index}",
  "点击跳转到此段落": "Click to jump to this passage",
  "正在载入章节…": "Loading chapter…",
  "章节暂时载入失败": "Chapter failed to load",
  "请刷新页面重试；没有完成音频的章节可以从工作台生成。":
    "Refresh the page and try again; chapters without finished audio can be generated from the workbench.",
  "选择章节开始试听": "Select a chapter to start listening",
  "没有完成音频的章节可以从工作台生成。":
    "Chapters without finished audio can be generated from the workbench.",

  // Emotion labels (constants.ts `emotions` values, shown in both pages)
  "默认": "Default",
  "平静": "Calm",
  "喜悦": "Joyful",
  "悲伤": "Sad",
  "愤怒": "Angry",
  "恐惧": "Fearful",
  "厌恶": "Disgusted",
  "惊讶": "Surprised",
  "激动": "Excited",
  "笑意": "Laughing",
  "温柔": "Gentle",
  "妩媚": "Charming",
  "娇喘": "Breathy",
  "耳语": "Whisper",
  "沉重": "Solemn",
  "哭腔": "Sobbing",
  "不安": "Anxious",
  "疑惑": "Confused",
  "嘲讽": "Sarcastic",
  "冷漠": "Indifferent",
  "结巴": "Stuttering",

  // Quality labels (constants.ts `qualityLabels` values, shown in Listen)
  "疑似静音": "Silent?",
  "时长异常": "Abnormal length",
  "疑似爆音": "Clipping?",
};

export default dict;
