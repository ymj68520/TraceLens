import { Link } from 'react-router-dom';

export default function CommunicationGraphEntry({ taskId }) {
  return <section className="space-y-4" aria-label="通讯关系图入口">
    <h2 className="text-lg font-semibold">通讯关系图</h2>
    <p className="text-sm text-slate-500">复用通讯取证中的关系分析，可查看账号联系、群组、时间分布和对应聊天记录。通讯账号与自然人身份分别保留。</p>
    <div className="flex flex-wrap gap-3">
      <Link className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white" to={`/im-forensics?tab=graph&task_id=${encodeURIComponent(taskId)}`}>查看当前任务通讯关系</Link>
      <Link className="rounded-lg border border-slate-300 px-4 py-2 text-sm" to="/im-forensics?platform=wechat&tab=graph">选择微信导入记录</Link>
      <Link className="rounded-lg border border-slate-300 px-4 py-2 text-sm" to="/im-forensics?platform=qq&tab=graph">选择 QQ 导入记录</Link>
    </div>
    <p className="text-xs text-slate-500">导入记录入口使用所选账号的数据范围；请在通讯页面核对来源。没有聊天记录不代表人员没有联系。</p>
  </section>;
}
