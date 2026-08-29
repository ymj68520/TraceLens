import { useAppDispatch, useAppSelector } from '../store';
import { updateSettings, resetSettings } from '../store/settingsSlice';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import { useToast } from '../components/ui/Toast';
import { useState } from 'react';
import type { Language } from '../types/locale';

export default function Settings() {
  const dispatch = useAppDispatch();
  const settings = useAppSelector((state) => state.settings);
  const toast = useToast();
  const [confirmReset, setConfirmReset] = useState(false);

  const set = (patch: Partial<typeof settings>) => dispatch(updateSettings(patch));

  return (
    <div className="space-y-4 max-w-3xl">
      <Card>
        <CardHeader title="显示设置" />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="field-label" htmlFor="set-theme">主题</label>
            <select
              id="set-theme"
              className="select"
              value={settings.theme}
              onChange={(e) => set({ theme: e.target.value as 'light' | 'dark' })}
            >
              <option value="light">浅色</option>
              <option value="dark">深色</option>
            </select>
          </div>
          <div>
            <label className="field-label" htmlFor="set-lang">语言</label>
            <select
              id="set-lang"
              className="select"
              value={settings.language}
              onChange={(e) => set({ language: e.target.value as Language })}
            >
              <option value="zh">中文</option>
              <option value="en">English</option>
            </select>
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader title="任务设置" />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="field-label" htmlFor="set-ipp">每页显示数量</label>
            <input
              id="set-ipp"
              type="number"
              min={5}
              max={200}
              className="input"
              value={settings.itemsPerPage}
              onChange={(e) => set({ itemsPerPage: Number(e.target.value) || 20 })}
            />
          </div>
          <div>
            <label className="field-label" htmlFor="set-interval">刷新间隔（毫秒）</label>
            <input
              id="set-interval"
              type="number"
              min={1000}
              step={500}
              className="input"
              value={settings.refreshInterval}
              onChange={(e) => set({ refreshInterval: Number(e.target.value) || 5000 })}
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-ink-700 dark:text-ink-300 sm:col-span-2">
            <input
              type="checkbox"
              className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
              checked={settings.autoRefresh}
              onChange={(e) => set({ autoRefresh: e.target.checked })}
            />
            自动刷新运行中的任务
          </label>
          <label className="flex items-center gap-2 text-sm text-ink-700 dark:text-ink-300 sm:col-span-2">
            <input
              type="checkbox"
              className="rounded border-ink-300 text-accent-600 focus:ring-accent-500"
              checked={settings.showTerminal}
              onChange={(e) => set({ showTerminal: e.target.checked })}
            />
            在导航中显示系统终端
          </label>
        </div>
      </Card>

      <Card>
        <CardHeader title="API 配置" subtitle="留空则使用默认推导地址" />
        <div className="grid grid-cols-1 gap-4">
          <div>
            <label className="field-label" htmlFor="set-api">C++ 后端地址</label>
            <input
              id="set-api"
              type="text"
              className="input font-mono text-xs"
              value={settings.apiUrl}
              onChange={(e) => set({ apiUrl: e.target.value })}
            />
          </div>
          <div>
            <label className="field-label" htmlFor="set-pyapi">Python 服务地址</label>
            <input
              id="set-pyapi"
              type="text"
              className="input font-mono text-xs"
              value={settings.pythonApiUrl}
              onChange={(e) => set({ pythonApiUrl: e.target.value })}
            />
          </div>
        </div>
      </Card>

      <div className="flex justify-end">
        <Button variant="ghost" className="text-rose-600" onClick={() => setConfirmReset(true)}>
          恢复默认设置
        </Button>
      </div>

      <ConfirmDialog
        open={confirmReset}
        title="恢复默认设置"
        message="所有自定义设置将被重置为默认值。"
        confirmText="重置"
        onConfirm={() => {
          dispatch(resetSettings());
          setConfirmReset(false);
          toast.success('已恢复默认设置');
        }}
        onCancel={() => setConfirmReset(false)}
      />
    </div>
  );
}
