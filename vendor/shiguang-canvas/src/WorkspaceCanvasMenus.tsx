import { useEffect, useRef, useState } from "react";
import { useCanvasStore } from "./store";

type MenuKind = "workspace" | "canvas" | "template" | null;

function promptName(label: string, defaultValue = ""): string | null {
  const v = window.prompt(label, defaultValue);
  if (v == null) return null;
  const trimmed = v.trim();
  return trimmed || null;
}

export default function WorkspaceCanvasMenus() {
  const activeProjectId = useCanvasStore((s) => s.activeProjectId);
  const activeProjectName = useCanvasStore((s) => s.activeProjectName);
  const activeCanvasId = useCanvasStore((s) => s.activeCanvasId);
  const activeCanvasName = useCanvasStore((s) => s.activeCanvasName);
  const ensureWorkspace = useCanvasStore((s) => s.ensureWorkspace);
  const listProjects = useCanvasStore((s) => s.listProjects);
  const createProject = useCanvasStore((s) => s.createProject);
  const openProject = useCanvasStore((s) => s.openProject);
  const renameProject = useCanvasStore((s) => s.renameProject);
  const deleteProject = useCanvasStore((s) => s.deleteProject);
  const listCanvases = useCanvasStore((s) => s.listCanvases);
  const createCanvas = useCanvasStore((s) => s.createCanvas);
  const switchCanvas = useCanvasStore((s) => s.switchCanvas);
  const renameCanvas = useCanvasStore((s) => s.renameCanvas);
  const deleteCanvas = useCanvasStore((s) => s.deleteCanvas);
  const duplicateCanvas = useCanvasStore((s) => s.duplicateCanvas);
  const listTemplates = useCanvasStore((s) => s.listTemplates);
  const saveTemplate = useCanvasStore((s) => s.saveTemplate);
  const loadTemplate = useCanvasStore((s) => s.loadTemplate);
  const deleteTemplate = useCanvasStore((s) => s.deleteTemplate);

  const [openMenu, setOpenMenu] = useState<MenuKind>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ensureWorkspace();
  }, [ensureWorkspace]);

  useEffect(() => {
    if (!openMenu) return;
    const onDoc = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpenMenu(null);
    };
    window.addEventListener("mousedown", onDoc);
    return () => window.removeEventListener("mousedown", onDoc);
  }, [openMenu]);

  const projects = listProjects();
  const canvases = listCanvases();
  const workspaceLabel = activeProjectName || "未命名工作区";
  const canvasLabel = activeCanvasName || "画布 1";

  const close = () => setOpenMenu(null);

  return (
    <div className="libtv-dd-group" ref={wrapRef}>
      <div className="libtv-dd-wrap">
        <button
          type="button"
          className={`libtv-dd${openMenu === "workspace" ? " on" : ""}`}
          onClick={() => setOpenMenu((m) => (m === "workspace" ? null : "workspace"))}
        >
          {workspaceLabel} ▾
        </button>
        {openMenu === "workspace" ? (
          <div className="libtv-dd-menu">
            <div className="libtv-dd-title">工作区</div>
            {projects.length === 0 ? (
              <div className="libtv-dd-empty">暂无工作区</div>
            ) : (
              projects.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className={`libtv-dd-item${p.id === activeProjectId ? " on" : ""}`}
                  onClick={() => {
                    openProject(p.id);
                    close();
                  }}
                >
                  <span>{p.name}</span>
                  <span className="libtv-dd-meta">{p.nodeCount} 节点</span>
                </button>
              ))
            )}
            <div className="libtv-dd-sep" />
            <button
              type="button"
              className="libtv-dd-item action"
              onClick={() => {
                const name = promptName("新建工作区名称", "未命名工作区");
                if (name) createProject(name);
                close();
              }}
            >
              + 新建工作区
            </button>
            {activeProjectId ? (
              <>
                <button
                  type="button"
                  className="libtv-dd-item action"
                  onClick={() => {
                    const name = promptName("重命名工作区", workspaceLabel);
                    if (name) renameProject(activeProjectId, name);
                    close();
                  }}
                >
                  重命名当前工作区
                </button>
                <button
                  type="button"
                  className="libtv-dd-item danger"
                  onClick={() => {
                    if (window.confirm(`删除工作区「${workspaceLabel}」？此操作不可恢复。`)) {
                      deleteProject(activeProjectId);
                      ensureWorkspace();
                    }
                    close();
                  }}
                >
                  删除当前工作区
                </button>
              </>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="libtv-dd-wrap">
        <button
          type="button"
          className={`libtv-dd${openMenu === "canvas" ? " on" : ""}`}
          onClick={() => setOpenMenu((m) => (m === "canvas" ? null : "canvas"))}
        >
          {canvasLabel} ▾
        </button>
        {openMenu === "canvas" ? (
          <div className="libtv-dd-menu">
            <div className="libtv-dd-title">画布</div>
            {canvases.map((c) => (
              <button
                key={c.id}
                type="button"
                className={`libtv-dd-item${c.id === activeCanvasId ? " on" : ""}`}
                onClick={() => {
                  switchCanvas(c.id);
                  close();
                }}
              >
                <span>{c.name}</span>
                <span className="libtv-dd-meta">{c.nodeCount} 节点</span>
              </button>
            ))}
            <div className="libtv-dd-sep" />
            <button
              type="button"
              className="libtv-dd-item action"
              onClick={() => {
                const name = promptName("新建画布名称", `画布 ${canvases.length + 1}`);
                createCanvas(name || undefined);
                close();
              }}
            >
              + 新建画布
            </button>
            {activeCanvasId ? (
              <>
                <button
                  type="button"
                  className="libtv-dd-item action"
                  onClick={() => {
                    const name = promptName("重命名画布", canvasLabel);
                    if (name) renameCanvas(activeCanvasId, name);
                    close();
                  }}
                >
                  重命名当前画布
                </button>
                <button
                  type="button"
                  className="libtv-dd-item action"
                  onClick={() => {
                    duplicateCanvas(activeCanvasId);
                    close();
                  }}
                >
                  复制当前画布
                </button>
                <button
                  type="button"
                  className="libtv-dd-item danger"
                  onClick={() => {
                    if (window.confirm(`删除画布「${canvasLabel}」？`)) {
                      deleteCanvas(activeCanvasId);
                    }
                    close();
                  }}
                >
                  删除当前画布
                </button>
              </>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="libtv-dd-wrap">
        <button
          type="button"
          className={`libtv-dd${openMenu === "template" ? " on" : ""}`}
          onClick={() => setOpenMenu((m) => (m === "template" ? null : "template"))}
        >
          模板 ▾
        </button>
        {openMenu === "template" ? (
          <div className="libtv-dd-menu">
            <div className="libtv-dd-title">✨ 快速开始</div>
            {listTemplates().filter((t) => t.builtin).map((t) => (
              <button
                key={t.id}
                type="button"
                className="libtv-dd-item"
                onClick={() => {
                  loadTemplate(t.id);
                  close();
                }}
              >
                <span style={{ fontWeight: 600 }}>{t.name}</span>
                {t.description ? (
                  <span style={{ display: "block", fontSize: 11, opacity: 0.7, marginTop: 2 }}>{t.description}</span>
                ) : null}
              </button>
            ))}
            <div className="libtv-dd-sep" />
            <div className="libtv-dd-title">我的模板</div>
            {listTemplates().filter((t) => !t.builtin).length === 0 ? (
              <div className="libtv-dd-empty">建好画布后点下方「+ 存为模板」</div>
            ) : (
              listTemplates().filter((t) => !t.builtin).map((t) => (
                <button
                  key={t.id}
                  type="button"
                  className="libtv-dd-item"
                  onClick={() => {
                    if (window.confirm(`加载模板「${t.name}」？将替换当前画布节点。`)) {
                      loadTemplate(t.id);
                    }
                    close();
                  }}
                >
                  <span>{t.name}</span>
                  <span className="libtv-dd-meta">
                    {t.savedAt ? new Date(t.savedAt).toLocaleDateString() : ""}
                  </span>
                </button>
              ))
            )}
            <div className="libtv-dd-sep" />
            <button
              type="button"
              className="libtv-dd-item action"
              onClick={() => {
                const name = promptName("保存当前画布为模板", "漫剧分镜工作流");
                if (name) saveTemplate(name);
                close();
              }}
            >
              + 存为模板
            </button>
            {listTemplates().filter((t) => !t.builtin).length > 0 ? (
              <button
                type="button"
                className="libtv-dd-item danger"
                onClick={() => {
                  const list = listTemplates().filter((t) => !t.builtin);
                  if (list.length === 0) return;
                  const target = list[list.length - 1];
                  if (window.confirm(`删除模板「${target.name}」？`)) {
                    deleteTemplate(target.id);
                  }
                  close();
                }}
              >
                删除最近模板
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
