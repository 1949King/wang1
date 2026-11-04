/**
 * 配方面板（左栏「配方」页）· 2026-10-19
 * ========================================
 * 独立组件，`CanvasShell.tsx` 只负责挂载（它属冻结区，体积余量只剩 16 行）。
 *
 * 三条交互纪律（与项目既有小白卡一致）：
 *   1. 点一下 = 铺开到画布（追加，不替换现有内容）
 *   2. 不弹二次确认 —— 铺开是**可撤销的加法**，不是破坏性操作
 *   3. 空态要说清楚「怎么才会有配方」：选中卡片 → 存为配方（存入口在卡片工具栏）
 */
import { useCallback, useEffect, useState } from "react";
import {
  applyRecipe,
  deleteRecipe,
  listRecipes,
  recipeSummary,
  type Recipe,
} from "./recipe";

export function RecipePanel({
  onStatus,
  refreshKey,
}: {
  onStatus: (msg: string) => void;
  /** 外部变更（新建/删除配方）后递增，触发重读 */
  refreshKey?: number;
}) {
  const [items, setItems] = useState<Recipe[]>([]);

  const refresh = useCallback(() => {
    setItems(listRecipes());
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, refreshKey]);

  const onApply = (r: Recipe) => {
    const ids = applyRecipe(r);
    if (ids.length === 0) {
      onStatus(`配方「${r.name}」没有卡片可铺`);
      return;
    }
    onStatus(`已按配方「${r.name}」铺开 ${ids.length} 张卡片`);
    refresh();
  };

  const onDelete = (r: Recipe) => {
    deleteRecipe(r.id);
    onStatus(`已删除配方「${r.name}」`);
    refresh();
  };

  return (
    <div>
      <div
        className="section-title"
        style={{ display: "flex", alignItems: "center", gap: 6 }}
      >
        配方
        <button
          type="button"
          className="btn"
          style={{ padding: "2px 6px" }}
          onClick={refresh}
          title="重新读取"
        >
          ↻
        </button>
      </div>

      {items.length === 0 ? (
        <p className="muted tiny">
          还没有配方。选中几张卡片 → 工具栏「存为配方」，下次点一下就能整套铺开。
        </p>
      ) : (
        items.map((r) => (
          <div
            key={r.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              marginBottom: 4,
            }}
          >
            <button
              type="button"
              className="btn"
              style={{ flex: 1, textAlign: "left" }}
              onClick={() => onApply(r)}
              title={r.intent.goal || r.name}
            >
              {recipeSummary(r)}
            </button>
            <button
              type="button"
              className="btn"
              style={{ padding: "2px 6px" }}
              onClick={() => onDelete(r)}
              title="删除这个配方"
            >
              ×
            </button>
          </div>
        ))
      )}
    </div>
  );
}
