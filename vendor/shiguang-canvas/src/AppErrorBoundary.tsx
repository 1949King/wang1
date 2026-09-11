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