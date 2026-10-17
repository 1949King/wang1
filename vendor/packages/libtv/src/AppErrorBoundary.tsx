import { Component, type ErrorInfo, type ReactNode } from "react";
import { useCanvasStore } from "./store";

type Props = { children: ReactNode };
type State = { error: Error | null; componentStack: string | null };

/**
 * 顶层错误边界：兜住画布任意渲染异常，避免 React 卸载整棵树后整页黑屏。
 *
 * 之前只有单节点 NodeErrorBoundary，属性面板/工具栏等一旦抛错，整个 <App/>
 * 会被卸载，只剩近黑背景。这里把「整页黑」降级为「可重试的错误面板」。
 */
export class AppErrorBoundary extends Component<Props, State> {
  state: State = { error: null, componentStack: null };

  static getDerivedStateFromError(error: Error): State {
    return { error, componentStack: null };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn("[canvas] app render crash", error, info.componentStack);
    // 保存组件栈，方便 UI 上展示定位
    this.setState({ componentStack: info.componentStack || null });
  }

  private handleRetry = () => {
    this.setState({ error: null, componentStack: null });
  };

  private handleClearSelectionAndRetry = () => {
    // 常见崩溃源是「选中节点后属性面板重渲染」；清空选中可避免刷新后原样回放同一崩溃
    try {
      useCanvasStore.getState().setSelected(null);
    } catch (e) {
      console.warn("[canvas] clear selection on crash failed", e);
    }
    this.setState({ error: null, componentStack: null });
  };

  render() {
    if (this.state.error) {
      const err = this.state.error;
      const stack = (err.stack || this.state.componentStack || "").trim();
      return (
        <div className="app-crash">
          <div className="app-crash-card">
            <div className="app-crash-title">画布遇到渲染错误</div>
            <pre className="app-crash-msg">{err.message || String(err)}</pre>
            {stack ? (
              <details className="app-crash-details">
                <summary>查看错误详情</summary>
                <pre className="app-crash-stack">{stack}</pre>
              </details>
            ) : null}
            <div className="app-crash-actions">
              <button type="button" className="btn primary" onClick={this.handleClearSelectionAndRetry}>
                清空选中并重试
              </button>
              <button type="button" className="btn" onClick={this.handleRetry}>
                重试
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

/**
 * 局部错误边界：包住单个面板 / 属性面板等子树。
 *
 * 为什么要有：顶层 AppErrorBoundary 一崩就是**整块画布**白屏（降级粒度太粗）。
 * 用本组件把「属性面板」「浮动面板」等子树各自包一层，单点渲染异常只把
 * **这一棵子树**降级成占位提示，画布其余部分照常可用；顶层边界退居最后兜底。
 * 样式用内联，避免改动冻结的 styles.css。
 */
export class SectionErrorBoundary extends Component<Props & { label?: string }, State> {
  state: State = { error: null, componentStack: null };

  static getDerivedStateFromError(error: Error): State {
    return { error, componentStack: null };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn(`[canvas] section render crash (${this.props.label || "unknown"})`, error, info.componentStack);
    this.setState({ componentStack: info.componentStack || null });
  }

  private handleRetry = () => {
    this.setState({ error: null, componentStack: null });
  };

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 12, fontSize: 12, color: "#f87171", lineHeight: 1.6 }}>
          ⚠️「{this.props.label || "该区域"}」渲染出错，已就地隔离，画布其余部分不受影响。
          <button
            type="button"
            onClick={this.handleRetry}
            style={{ marginLeft: 8, fontSize: 12, cursor: "pointer" }}
          >
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}