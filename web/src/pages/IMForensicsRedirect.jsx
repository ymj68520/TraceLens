// IMForensicsRedirect.jsx
// 微信取证 / QQ 取证 / 微信关系分析 三页已于 2026-09-15 合并为 /im-forensics
// （pages/IMForensics/IMForensics.jsx）。保留路由级重定向并映射查询参数，
// 防止旧链接/书签 404 —— 与 /investigation-graph → /investigation 同理；
// 确认无外部依赖后再物理删除这些路由。
import { Navigate, useSearchParams } from 'react-router-dom';

const toTarget = (params) => {
  const query = params.toString();
  return query ? `/im-forensics?${query}` : '/im-forensics';
};

/** /wechat-forensics、/qq-forensics → /im-forensics?platform=…（丢弃 task_id，旧页并不消费它） */
const ForensicsRedirect = ({ platform }) => {
  const [searchParams] = useSearchParams();
  const params = new URLSearchParams(searchParams);
  params.delete('task_id');
  params.set('platform', platform);
  return <Navigate to={toTarget(params)} replace />;
};

export const WeChatForensicsRedirect = () => <ForensicsRedirect platform="wechat" />;
export const QQForensicsRedirect = () => <ForensicsRedirect platform="qq" />;

/** /wechat-graph?task_id=X → /im-forensics?tab=graph…；wx_/qq_ 前缀映射为平台+导入选择 */
export const WeChatGraphRedirect = () => {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id') || '';
  if (taskId.startsWith('wx_') || taskId.startsWith('qq_')) {
    const platform = taskId.startsWith('qq_') ? 'qq' : 'wechat';
    return (
      <Navigate
        to={`/im-forensics?platform=${platform}&import_id=${encodeURIComponent(taskId.slice(3))}&tab=graph`}
        replace
      />
    );
  }
  const params = new URLSearchParams(searchParams);
  params.set('tab', 'graph');
  return <Navigate to={toTarget(params)} replace />;
};
