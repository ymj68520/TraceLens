import { useEffect, useRef, useState } from 'react';
import { translateInitialAnalysis } from '../../../services/investigationService';

export function initialAnalysisText(payload = {}) {
  const description = payload.initial_description || '';
  const summary = payload.initial_summary || '';
  if (description && summary && description !== summary) {
    return `摘要：${summary}\n\n详细描述：${description}`;
  }
  return description || summary;
}

export function needsChineseTranslation(text = '') {
  const latin = (text.match(/[A-Za-z]/g) || []).length;
  const han = (text.match(/[\u4e00-\u9fff]/g) || []).length;
  return latin >= 40 && latin > han * 1.5;
}

export default function useInitialAnalysisTranslation(taskId, evidenceKey, sourceText) {
  const identity = `${taskId || ''}\u0000${evidenceKey || ''}\u0000${sourceText || ''}`;
  const [state, setState] = useState({ identity: null, text: null, loading: false, translated: false, error: null });
  const requestIdRef = useRef(0);

  useEffect(() => {
    const requestId = ++requestIdRef.current;
    if (!sourceText || !taskId || !evidenceKey) {
      setState({ identity, text: sourceText || null, loading: false, translated: false, error: null });
      return undefined;
    }
    if (!needsChineseTranslation(sourceText)) {
      setState({ identity, text: sourceText, loading: false, translated: false, error: null });
      return undefined;
    }
    setState({ identity, text: null, loading: true, translated: false, error: null });
    translateInitialAnalysis(taskId, evidenceKey).then((result) => {
      if (requestId !== requestIdRef.current) return;
      setState({
        identity,
        text: result.text || null,
        loading: false,
        translated: Boolean(result.translated),
        error: null,
      });
    }).catch((error) => {
      if (requestId !== requestIdRef.current) return;
      setState({ identity, text: sourceText, loading: false, translated: false, error });
    });
    return () => { requestIdRef.current += 1; };
  }, [taskId, evidenceKey, sourceText]);

  if (state.identity !== identity) {
    return {
      text: needsChineseTranslation(sourceText) ? null : sourceText || null,
      loading: Boolean(sourceText && taskId && evidenceKey && needsChineseTranslation(sourceText)),
      translated: false,
      error: null,
    };
  }
  return state;
}
