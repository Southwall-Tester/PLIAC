import {Component, lazy, memo, Suspense, type ReactNode} from 'react';

const Content = lazy(() => import('./RichTextContent'));

class RenderBoundary extends Component<{text: string; children: ReactNode}, {failed: boolean}> {
  state = {failed: false};
  static getDerivedStateFromError() {return {failed: true};}
  render() {
    return this.state.failed ? <><p className="quiet-note">排版组件未能加载，先保留原文；刷新页面后可重试。</p>
      <p style={{whiteSpace: 'pre-wrap'}}>{this.props.text}</p></> : this.props.children;
  }
}

export const RichText = memo(function RichText({text}: {text: string}) {
  return <div className="rich-text"><RenderBoundary text={text}><Suspense fallback={<p style={{whiteSpace: 'pre-wrap'}}>{text}</p>}>
    <Content text={text}/>
  </Suspense></RenderBoundary></div>;
});
