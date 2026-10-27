import { forensicLabel, forensicError } from '../../utils/forensicLabels';
export default function ReportStatusPanel({ versions, version, incompatible = false }) {
  if (!versions.length) {
    return <div role="status">尚未生成报告</div>;
  }

  if (incompatible) {
    return <div role="alert">当前报告模式不兼容，请生成新版本。</div>;
  }

  if (version?.status === 'queued' || version?.status === 'generating') {
    return <div role="status">{forensicLabel(version.status)} · {version.progress}%</div>;
  }

  if (version?.status === 'failed') {
    return <div role="alert">报告生成失败：{forensicError(version.error)}</div>;
  }

  return null;
}
