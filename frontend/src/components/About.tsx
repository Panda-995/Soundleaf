import {
  ArrowUpRight,
  AudioLines,
  BookOpen,
  FileText,
  Headphones,
  Mail,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { APP_VERSION } from "../constants";
import { t } from "../i18n";

const FEATURES = [
  { icon: BookOpen, title: "导入与分章", desc: "TXT、EPUB 自动识别章节" },
  { icon: Sparkles, title: "AI 导演", desc: "分段、角色与情绪建议" },
  { icon: AudioLines, title: "音色与合成", desc: "角色绑定音色，逐段合成" },
  { icon: Headphones, title: "试听与导出", desc: "倍速播放，导出 MP3 / M4B" },
] as const;

const EMAIL = "676096193@qq.com";

export function About() {
  return (
    <section className="panel settings-panel about-panel">
      <div className="about-hero">
        <div className="about-brand">
          <AudioLines size={30} />
          <h2>声页</h2>
          <span>{t("小说转有声书的本地工作室")}</span>
        </div>
        <p>
          {t(
            "把 TXT / EPUB 小说变成可以听见的有声书：导入分章、AI 分段与角色建议、角色绑定音色、逐段合成，再到试听与导出，全部在你的设备上完成。",
          )}
        </p>
        <div className="about-features">
          {FEATURES.map(({ icon: Icon, title, desc }) => (
            <div key={title}>
              <Icon size={19} />
              <b>{t(title)}</b>
              <span>{t(desc)}</span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <h3 className="about-heading">
          <ShieldCheck size={17} />
          {t("合规与支持")}
        </h3>
        <p className="muted">{t("查看隐私规则与个人信息清单，或通过以下渠道反馈问题。")}</p>
        <div className="about-links">
          <a href="/privacy-policy.html" target="_blank" rel="noopener noreferrer">
            <FileText size={16} />
            <span>
              <b>{t("隐私政策")}</b>
              <small>{t("了解各项功能如何处理个人信息")}</small>
            </span>
            <ArrowUpRight size={14} />
          </a>
          <a
            href="/privacy-policy.html#personal-information-lists"
            target="_blank"
            rel="noopener noreferrer"
          >
            <ShieldCheck size={16} />
            <span>
              <b>{t("个人信息“双清单”")}</b>
              <small>{t("已收集信息与第三方共享清单")}</small>
            </span>
            <ArrowUpRight size={14} />
          </a>
          <a href={"mailto:" + EMAIL}>
            <Mail size={16} />
            <span>
              <b>{t("投诉、举报与反馈")}</b>
              <small>{EMAIL}</small>
            </span>
            <ArrowUpRight size={14} />
          </a>
        </div>
      </div>

      <div className="about-dev">
        <p>
          <b>{t("开发者与发布者：")}</b>
          熊猫不是猫QAQ（{t("个人开发者，非企业主体")}）
        </p>
        <p>
          <b>{t("办公信息：")}</b>
          {t("个人开发者远程办公，无企业注册地址或固定对外办公场所")}
        </p>
        <p>
          <b>{t("个人信息保护负责人及投诉邮箱：")}</b>
          <a href={"mailto:" + EMAIL}>{EMAIL}</a>
        </p>
        <p className="muted">
          {t(
            "声页为自托管软件，数据保存在你自己的设备上；若实例由他人部署，实际运营信息以该部署者公示为准。",
          )}
        </p>
      </div>

      <footer className="about-foot">
        <p>{t("© 2026 熊猫不是猫QAQ · 本地运行，数据自持")}</p>
        <p className="muted">声页 · {APP_VERSION}</p>
      </footer>
    </section>
  );
}
