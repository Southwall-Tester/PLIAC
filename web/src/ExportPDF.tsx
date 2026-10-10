import {useEffect, useRef, useState} from 'react';
import {useParams} from 'react-router-dom';
import {localLearner} from './api';

export function ExportPDF({kind, id}: {kind: 'material' | 'report' | 'textbook'; id: string}) {
  const {courseId = ''} = useParams();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const abort = useRef<AbortController | null>(null);
  useEffect(() => {
    setBusy(false); setError('');
    return () => abort.current?.abort();
  }, [courseId, kind, id]);
  function cancel() {
    abort.current?.abort();
    setBusy(false);
    setError('已取消本次下载等待，学习成果仍保留；服务端排版可能仍在完成。');
  }
  async function download() {
    if (busy) return;
    const controller = new AbortController(); abort.current = controller;
    setBusy(true); setError('');
    try {
      const query = new URLSearchParams({course_id: courseId, student_id: localLearner(), kind, artifact_id: id});
      const response = await fetch(`/api/tutor/export/pdf?${query}`, {signal: controller.signal});
      if (!response.ok) {
        const problem = await response.json();
        throw new Error(typeof problem.detail === 'string' ? problem.detail : '导出未完成，请重试。');
      }
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = `${kind}-${id}.pdf`;
      document.body.appendChild(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '网络异常，请重试。');
    } finally {if (!controller.signal.aborted) setBusy(false);}
  }
  return <div><button disabled={busy} onClick={download}>{busy ? '正在导出…' : '导出 PDF'}</button>
    {busy && <button onClick={cancel}>取消下载等待</button>}
    {error && <p role="alert">{error}</p>}</div>;
}
