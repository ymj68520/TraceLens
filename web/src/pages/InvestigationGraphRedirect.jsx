// InvestigationGraphRedirect.jsx
// /investigation-graph 已并入调查工作台（中栏 Graph Tab）。保留路由级
// 重定向并透传 task 参数，防止旧链接/书签 404 —— f29050b 曾因路由丢失
// 导致侧边栏 404；确认无外部依赖后再物理删除该路由。
import { Navigate, useSearchParams } from 'react-router-dom';

const InvestigationGraphRedirect = () => {
  const [searchParams] = useSearchParams();
  const search = searchParams.toString();
  return <Navigate to={search ? `/investigation?${search}` : '/investigation'} replace />;
};

export default InvestigationGraphRedirect;
