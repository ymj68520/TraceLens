import { useEffect, useMemo, useState } from 'react';

const EMPTY_STATE = { key: null, data: null, loading: false, error: null };

export function useReportCategory({ dataSource, reportId, categoryId, page }) {
  const requestKey = useMemo(
    () => (reportId && categoryId && Number.isFinite(page) && page > 0
      ? `${reportId}::${categoryId}::${page}`
      : null),
    [categoryId, page, reportId],
  );
  const [state, setState] = useState(EMPTY_STATE);

  useEffect(() => {
    if (!requestKey) {
      setState(EMPTY_STATE);
      return undefined;
    }

    let active = true;
    setState({ key: requestKey, data: null, loading: true, error: null });
    Promise.resolve(dataSource.getCategoryPage(reportId, categoryId, page))
      .then((data) => {
        if (active) setState({ key: requestKey, data, loading: false, error: null });
      })
      .catch((error) => {
        if (active) setState({ key: requestKey, data: null, loading: false, error });
      });

    return () => { active = false; };
  }, [categoryId, dataSource, page, reportId, requestKey]);

  if (state.key !== requestKey) {
    return { data: null, loading: Boolean(requestKey), error: null };
  }
  return { data: state.data, loading: state.loading, error: state.error };
}
