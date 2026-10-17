import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  nodeId?: string;
  nodeType?: string;
  children: ReactNode;
};

type State = { error: Error | null };

/** 单节点崩溃时只替换该卡，不白屏整张画布 */
export class NodeErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn("[canvas] node crash", this.props.nodeType, this.props.nodeId, error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="sg-node sg-node-crash">
          <div className="head">节点渲染失败</div>
          <div className="body">
            <div className="muted tiny">
              {this.props.nodeType || "unknown"}
              {this.props.nodeId ? ` · ${this.props.nodeId}` : ""}
            </div>
            <pre className="sg-node-crash-msg">{this.state.error.message}</pre>
            <button
              type="button"
              className="btn nodrag nopan"
              onClick={() => this.setState({ error: null })}
            >
              重试渲染
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
