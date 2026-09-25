// Dictionary for Library.tsx, Queue.tsx, Voices.tsx and Export.tsx (group A).
// Keys are the exact zh source strings; t()/tf() fall back to the key itself.
// Shared keys already covered by core/groupB/groupC ("取消", "章节", "时长",
// "任务队列", "导入小说", "AI 分析", "AI 章节识别", "音色试听", "未生成",
// "音频版本", "{count} 章") are not repeated here, so those groups' wording
// wins the merge and stays consistent across pages.
const dict: Record<string, string> = {
  // Library — AI flow notifications
  "AI 没有返回书籍资料": "The AI returned no book metadata",
  "AI 封面已生成并应用到书籍。": "The AI cover was generated and applied to the book.",
  "封面生成未完成": "Cover generation did not finish",
  "分析未完成": "Analysis did not finish",
  "AI 任务失败：{message}": "AI job failed: {message}",
  "AI 任务仍在后台运行，完成后可在任务队列查看结果。":
    "The AI job keeps running in the background; check the job queue for the result when it finishes.",
  "书籍资料已应用。": "Book metadata applied.",

  // Library — AI entry points
  "AI 分析书籍": "Analyze book with AI",
  "AI 分析《{title}》": 'Analyze "{title}" with AI',
  "AI 分析书籍资料": "Analyze book metadata with AI",

  // Library — delete dialog
  "删除《{title}》？": 'Delete "{title}"?',
  "将删除本书及其全部章节、音频、导出包、任务、播放进度和封面。原始上传文件也会被移除。共享语音缓存保留。 这项操作不可撤销。":
    "This deletes the book along with all chapters, audio, export packages, jobs, playback progress and the cover. The original uploaded file is removed too. The shared voice cache is kept. This action cannot be undone.",
  "{done} / {total} 章已完成 · 删除前请先确认导出或备份。":
    "{done} / {total} chapters done · Export or back up before deleting.",
  "已移除书籍，有 {count} 个文件因权限问题未清理":
    "Book removed; {count} files could not be cleaned up due to permission issues",
  "已删除《{title}》": 'Deleted "{title}"',
  "确认删除": "Delete",

  // Library — heading, empty states, continue section
  "我的书架": "My Library",
  "把每一页，变成可以听见的故事。": "Turn every page into a story you can hear.",
  "第一本有声书，从这里开始": "Your first audiobook starts here",
  "上传 TXT 或 EPUB，挑一个声音，让熟悉的故事有新的模样。":
    "Upload a TXT or EPUB, pick a voice, and give a familiar story a new shape.",
  "导入第一本小说": "Import your first novel",
  "配置语音服务": "Set up voice service",
  "继续制作": "Continue",
  "未填写作者": "Author unknown",
  "{author} · {count} 章": "{author} · {count} chapters",
  "{done} / {total} 章已完成": "{done} / {total} chapters done",
  "删除书籍": "Delete book",
  "全部作品": "All books",
  "搜索书籍": "Search books",
  "搜索书名、作者": "Search title or author",
  "打开《{title}》": 'Open "{title}"',
  "删除《{title}》": 'Delete "{title}"',
  "没有找到这本书": "No matching book",
  "换一个关键词试试。": "Try a different keyword.",

  // Queue
  "正在读取队列": "Loading queue",
  "关闭页面后，任务仍会继续。": "Jobs keep running after you close the page.",
  "恢复队列": "Resume queue",
  "暂停队列": "Pause queue",
  "已暂停领取新任务。当前正在处理的任务会继续到结束。":
    "Paused: no new jobs will be picked up. The job in progress runs to completion.",
  "正在制作": "In progress",
  "短试听": "Short preview",
  "音色测试": "Voice test",
  "{done} / {total} 片段": "{done} / {total} segments",
  "批量导出": "Batch export",
  "章节生成": "Chapter generation",
  "确认重试": "Confirm retry",
  "重试使用原任务的模型与文本快照。如果服务配置已修改，请取消此任务并从章节页重新生成。":
    "Retrying uses the original job's model and text snapshot. If the service configuration has changed, cancel this job and regenerate from the chapter page.",
  "结果待确认的请求可能已经计费，重试前请检查服务商记录。":
    'Requests marked "needs review" may already have been billed; check your provider records before retrying.',
  "重试": "Retry",
  "取消任务": "Cancel job",
  "取消正在处理的任务？": "Cancel the running job?",
  "任务会在安全边界停止；已经提交给语音服务的请求可能仍会完成并产生费用。":
    "The job stops at a safe boundary; requests already sent to the voice service may still complete and incur charges.",
  "继续处理": "Keep running",
  "确认取消": "Confirm cancel",
  "试听任务成品": "Preview the job's audio",
  "还没有制作任务": "No jobs yet",
  "选定章节或试听一个音色后，可以在这里查看进度。":
    "Generate a chapter or preview a voice, and progress shows up here.",
  "打开章节工作台": "Open chapter workbench",

  // statusText values from constants.ts, translated at usage sites
  "等待中": "Queued",
  "处理中": "Running",
  "已完成": "Done",
  "失败": "Failed",
  "结果待确认": "Needs review",
  "已取消": "Cancelled",

  // Voices
  "暮色落进海面的时候，他收到了一封没有署名的信。":
    "As dusk settled over the sea, he received an unsigned letter.",
  "为故事挑选声音": "Pick voices for your story",
  "同一段文字，听见不同的表达。": "The same text, heard in different voices.",
  "已获取 {count} 个音色": "Fetched {count} voices",
  "同步音色": "Sync voices",
  "全部音色": "All voices",
  "已收藏": "Favorites",
  "搜索音色": "Search voices",
  "搜索声音与特征": "Search voices and traits",
  "收藏音色": "Favorite voice",
  "试听音色": "Preview voice",
  "没有匹配的音色": "No matching voices",
  "同步服务商音色，或在设置中填写自定义音色 ID。":
    "Sync provider voices, or enter a custom voice ID in settings.",
  "选择一个声音": "Choose a voice",
  "支持情绪与语速": "Supports emotion and speed",
  "支持语速 · 默认情绪": "Supports speed · default emotion",
  "试听文本": "Preview text",
  "试听声音": "Preview voice",
  "已应用到本书，已有章节音频将标记为待更新。":
    "Applied to this book; existing chapter audio will be marked as outdated.",
  "应用到《{title}》": 'Apply to "{title}"',
  "短试听会使用当前语音服务并可能计费。":
    "A short preview uses the current voice service and may incur charges.",

  // Export
  "导出有声书": "Export audiobook",
  "每章独立保存，也可以一次带走。": "Save chapters individually, or take them all at once.",
  "选择章节": "Select chapters",
  "全选已完成": "Select all completed",
  "导出{title}": "Export {title}",
  " · 待更新": " · needs update",
  "未生成的章节不会包含在导出包中。单章也可从试听页直接下载。":
    "Chapters without audio are not included in the export package. Single chapters can also be downloaded from the listen page.",
  "导出历史": "Export history",
  "刷新": "Refresh",
  "下载": "Download",
  "导出设置": "Export settings",
  "音频格式": "Audio format",
  "导出音频格式": "Export audio format",
  "MP3 · 逐章文件 + ZIP 打包": "MP3 · per-chapter files + ZIP archive",
  "WAV · 逐章文件 + ZIP 打包": "WAV · per-chapter files + ZIP archive",
  "M4B · 单文件章节有声书": "M4B · single-file chaptered audiobook",
  "章节导航": "Chapter navigation",
  "播放器中显示章节列表": "Shows a chapter list in the player",
  "嵌入元数据（书名/作者/章节）与封面": "Embed metadata (title/author/chapters) and cover",
  "封面嵌入": "Cover embedding",
  "将嵌入当前封面": "Current cover will be embedded",
  "未设置封面": "No cover set",
  "到书架上传封面后重新导出，MP3 会自动附带封面插图（元数据不受影响）。":
    "Upload a cover in the library and export again; MP3 files will then carry the cover image automatically (metadata is unaffected).",
  "文件名示例": "Filename example",
  "有声书": "Audiobook",
  "第一章": "Chapter 1",
  "允许导出尚未更新的旧音频": "Allow exporting outdated audio",
  "已选择": "Selected",
  "导出任务已加入队列，完成后从导出历史下载。":
    "Export job queued; download it from the export history when it finishes.",
  "创建导出包": "Create export package",
  "导出会固定当前音频版本，后续修改不会改变这次包内容。":
    "Exporting locks in the current audio versions; later edits will not change this package.",
};

export default dict;
