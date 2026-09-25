import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Save } from "lucide-react";
import { Button } from "./ui";
import { api } from "../api";
import { t } from "../i18n";

/** Change-password form shared by the forced first-login dialog and the
 * Settings account tab. Inputs are uncontrolled (read once on submit), so no
 * keystroke re-renders the fields and IME composition stays intact — same
 * contract as the auth form and BookAiModal. Errors render inline because the
 * global toast would sit behind a showModal() dialog's backdrop. */
export function PasswordForm({ onSaved }: { onSaved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        const d = new FormData(e.currentTarget);
        const next = d.get("password");
        if (next !== d.get("confirm")) {
          setError(t("两次输入的新密码不一致"));
          return;
        }
        setBusy(true);
        setError("");
        api("/account/password", "POST", {
          current: d.get("current"),
          password: next,
        })
          .then(onSaved)
          .catch((e) => setError(e.message))
          .finally(() => setBusy(false));
      }}
    >
      <label>
        {t("当前密码")}
        <input
          name="current"
          type="password"
          autoComplete="current-password"
          maxLength={200}
          required
          autoFocus
        />
      </label>
      <label>
        {t("新密码")}
        <input
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={8}
          maxLength={200}
          required
          placeholder={t("至少 8 位")}
        />
      </label>
      <label>
        {t("确认新密码")}
        <input
          name="confirm"
          type="password"
          autoComplete="new-password"
          minLength={8}
          maxLength={200}
          required
          placeholder={t("再输入一次新密码")}
        />
      </label>
      <div className="actions">
        <Button primary type="submit" disabled={busy}>
          {busy ? <LoaderCircle className="spin" size={16} /> : null}
          <Save size={16} />
          {t("保存新密码")}
        </Button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </form>
  );
}

/** First-login gate: while the account still carries the seeded default
 * password, the studio opens only through this dialog. It intentionally
 * cannot be dismissed (no close button, Escape ignored) — replacing default
 * credentials is the one step that must happen, like a first-run setup. */
export function PasswordDialog({ onDone }: { onDone: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby="password-dialog-title"
      onCancel={(e) => e.preventDefault()}
    >
      <div className="dialog-head">
        <h2 id="password-dialog-title">{t("请修改默认密码")}</h2>
      </div>
      <div className="dialog-content">
        <p>
          {t(
            "你正在使用默认账户和默认密码。为保护你的书籍与服务配置，请先设置一个新密码。",
          )}
        </p>
        <PasswordForm onSaved={onDone} />
      </div>
    </dialog>
  );
}
