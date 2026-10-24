import { useState } from "react";
import { usePluginStore } from "./plugins/plugin-store";
import {
  installPluginFromUrl,
  setPluginEnabled,
  uninstallPlugin,
} from "./plugins/plugin-loader";

type Props = {
  onStatus?: (msg: string) => void;
};

export default function PluginManagerPanel({ onStatus }: Props) {
  const plugins = usePluginStore((s) => s.plugins);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);

  const notify = (msg: string) => onStatus?.(msg);

  const handleInstall = async () => {
    const u = url.trim();
    if (!u) return;
    setBusy(true);
    try {
      const p = await installPluginFromUrl(u);
      notify(`已安装插件「${p.name || p.id}」· ${p.nodes.length} 个节点`);
      setUrl("");
    } catch (e) {
      notify(`安装失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="plugin-manager">
      <div className="plugin-install-row">
        <input
          className="plugin-url-input"
          placeholder="插件 bundle URL…"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void handleInstall();
          }}
        />
        <button type="button" className="btn teal" disabled={busy || !url.trim()} onClick={() => void handleInstall()}>
          安装
        </button>
      </div>
      {plugins.length === 0 ? (
        <p className="muted plugin-empty">暂无插件。可放 bundle 到 public/plugins/ 并在 index.json 列出。</p>
      ) : (
        <ul className="plugin-list">
          {plugins.map((p) => (
            <li key={p.id} className={`plugin-item${p.enabled ? " on" : ""}`}>
              <div className="plugin-item-head">
                <strong>{p.name || p.id}</strong>
                <span className="muted">v{p.version}</span>
                {p.local ? <span className="plugin-tag">本地</span> : null}
                {p.official ? <span className="plugin-tag official">官方</span> : null}
              </div>
              {p.description ? <p className="plugin-desc">{p.description}</p> : null}
              <div className="plugin-item-actions">
                <label className="plugin-toggle">
                  <input
                    type="checkbox"
                    checked={p.enabled}
                    onChange={async (e) => {
                      setBusy(true);
                      try {
                        await setPluginEnabled(p, e.target.checked);
                        notify(e.target.checked ? `已启用 ${p.name}` : `已禁用 ${p.name}`);
                      } catch (err) {
                        notify(`切换失败：${err instanceof Error ? err.message : String(err)}`);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  />
                  启用
                </label>
                <button
                  type="button"
                  className="btn danger sm"
                  disabled={busy}
                  onClick={() => {
                    uninstallPlugin(p.id);
                    notify(`已卸载 ${p.name || p.id}`);
                  }}
                >
                  卸载
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
