import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { getLocalOperatorSession, localReturnPath } from '../services/localOperatorSession';
import { setFieldSession } from '../services/fieldSession';

export default function LocalOperatorEntry() {
  const navigate = useNavigate();
  const location = useLocation();
  const target = localReturnPath(location.state?.returnTo);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setFailed(false);
    getLocalOperatorSession().then((session) => {
      if (!active) return;
      setFieldSession(session.access_token, session.principal);
      navigate(target, { replace: true });
    }).catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [navigate, target, attempt]);
  return <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950">
    <div className="text-center text-slate-600 dark:text-slate-300" role="status">
      <p>{failed ? '本机入口暂不可用，请检查本机服务。' : '正在进入本机工作台…'}</p>
      {failed && <button className="mt-4 px-4 py-2 rounded-lg bg-primary-600 text-white"
        onClick={() => setAttempt((value) => value + 1)}>重试</button>}
    </div>
  </div>;
}
