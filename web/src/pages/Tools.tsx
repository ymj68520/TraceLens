import { useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import { BarChart3, Binary, Clock, Hash, Network, Regex, Wrench } from 'lucide-react';
import { PageHeader, Segmented } from '../components/ui/PageScaffold';
import HashTool from './tools/HashTool';
import TimestampTool from './tools/TimestampTool';
import RegexTool from './tools/RegexTool';
import EncodeTool from './tools/EncodeTool';
import TextStatsTool from './tools/TextStatsTool';
import NetworkTool from './tools/NetworkTool';

/* ---------------------------------------------------------------------------
 * 小工具：取证人员日常使用的离线工具集。
 * 全部工具纯前端计算、无网络请求；这里只做 Segmented 编排，
 * 按需渲染当前工具，具体实现见 pages/tools/ 下各子组件。
 * ------------------------------------------------------------------------- */

type ToolId = 'hash' | 'timestamp' | 'regex' | 'encode' | 'textstats' | 'network';

const TOOLS: Array<{ id: ToolId; label: string; icon: LucideIcon }> = [
  { id: 'hash', label: '哈希计算', icon: Hash },
  { id: 'timestamp', label: '时间戳转换', icon: Clock },
  { id: 'regex', label: '正则测试', icon: Regex },
  { id: 'encode', label: '编码转换', icon: Binary },
  { id: 'textstats', label: '文本统计', icon: BarChart3 },
  { id: 'network', label: 'IP 计算', icon: Network },
];

export default function Tools() {
  const [active, setActive] = useState<ToolId>('hash');

  return (
    <div className="max-w-5xl">
      <PageHeader
        icon={Wrench}
        tone="slate"
        title="小工具"
        subtitle="取证日常离线工具集，数据不出浏览器"
      />

      <Segmented
        options={TOOLS.map((t) => ({ value: t.id, label: t.label, icon: t.icon }))}
        value={active}
        onChange={setActive}
        className="mb-4"
      />

      {active === 'hash' && <HashTool />}
      {active === 'timestamp' && <TimestampTool />}
      {active === 'regex' && <RegexTool />}
      {active === 'encode' && <EncodeTool />}
      {active === 'textstats' && <TextStatsTool />}
      {active === 'network' && <NetworkTool />}
    </div>
  );
}
