import { motion } from 'framer-motion';
import { useState, useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { updateSettings, resetSettings } from '../store/settingsSlice';
import { useTranslation } from '../hooks/useTranslation';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import { getLLMStatus, getModels } from '../services/llmService';
import { getGraphitiStatus } from '../services/graphitiService';

const Settings = () => {
  const dispatch = useDispatch();
  const settings = useSelector((state) => state.settings);
  const { t } = useTranslation();

  // LLM model info
  const [llmInfo, setLlmInfo] = useState(null);
  const [llmLoading, setLlmLoading] = useState(false);

  // Neo4j test
  const [neo4jStatus, setNeo4jStatus] = useState(null);
  const [neo4jTesting, setNeo4jTesting] = useState(false);

  const handleSettingChange = (key, value) => {
    dispatch(updateSettings({ [key]: value }));
  };

  const handleReset = () => {
    if (window.confirm(t('settings.reset_confirm'))) {
      dispatch(resetSettings());
    }
  };

  // Load LLM model info
  const loadLLMInfo = async () => {
    setLlmLoading(true);
    try {
      const [status, models] = await Promise.all([
        getLLMStatus().catch(() => ({ status: 'error' })),
        getModels().catch(() => ({ models: [] })),
      ]);
      setLlmInfo({ ...status, models: models.models || models });
    } catch {
      setLlmInfo({ status: 'error' });
    } finally {
      setLlmLoading(false);
    }
  };

  // Test Neo4j connection
  const testNeo4j = async () => {
    setNeo4jTesting(true);
    try {
      const status = await getGraphitiStatus();
      setNeo4jStatus(status);
    } catch (err) {
      setNeo4jStatus({ neo4j_connected: false, error: err.message });
    } finally {
      setNeo4jTesting(false);
    }
  };

  useEffect(() => {
    loadLLMInfo();
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <motion.h1 initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="text-3xl font-bold text-slate-900 dark:text-slate-100">{t('settings.title')}</motion.h1>
        <p className="mt-2 text-slate-600 dark:text-slate-400">{t('settings.subtitle')}</p>
      </div>

      <Card title={t('settings.api_config')}>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('settings.api_url')} (C++ 后端)
            </label>
            <input
              type="text"
              value={settings.apiUrl}
              onChange={(e) => handleSettingChange('apiUrl', e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 dark:bg-slate-700 dark:text-white"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              Python 服务 URL
            </label>
            <input
              type="text"
              value={settings.pythonApiUrl}
              onChange={(e) => handleSettingChange('pythonApiUrl', e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 dark:bg-slate-700 dark:text-white"
            />
          </div>
        </div>
      </Card>

      {/* LLM Model Configuration */}
      <Card title="🧠 LLM 模型配置">
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className={`w-2.5 h-2.5 rounded-full ${(llmInfo?.status === 'healthy' || llmInfo?.status === 'available') ? 'bg-green-500' : 'bg-red-500'}`} />
              <span className="text-sm font-medium text-slate-900 dark:text-white">
                状态: {(llmInfo?.status === 'healthy' || llmInfo?.status === 'available') ? '在线' : llmInfo?.status === 'error' ? '离线' : '未知'}
              </span>
            </div>
            <Button variant="outline" size="sm" onClick={loadLLMInfo} disabled={llmLoading}>
              {llmLoading ? <Spinner size="sm" /> : '🔄 刷新'}
            </Button>
          </div>

          {llmInfo && llmInfo.status !== 'error' && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Text Model */}
              <div className="p-4 bg-slate-50 dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700">
                <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">📝 文本模型</h4>
                <div className="space-y-1 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate-500">模型:</span>
                    <span className="font-mono text-slate-900 dark:text-white">{llmInfo.text_model?.name || (typeof llmInfo.text_model === 'string' ? llmInfo.text_model : '-')}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Base URL:</span>
                    <span className="font-mono text-slate-900 dark:text-white text-xs">{llmInfo.text_model?.base_url || llmInfo.text_base_url || '-'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Max Tokens:</span>
                    <span className="font-mono">{llmInfo.text_max_tokens || '-'}</span>
                  </div>
                </div>
              </div>

              {/* Vision Model */}
              <div className="p-4 bg-slate-50 dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700">
                <h4 className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">👁️ 视觉模型</h4>
                <div className="space-y-1 text-sm">
                  <div className="flex justify-between">
                    <span className="text-slate-500">模型:</span>
                    <span className="font-mono text-slate-900 dark:text-white">{llmInfo.vision_model?.name || (typeof llmInfo.vision_model === 'string' ? llmInfo.vision_model : '-')}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Base URL:</span>
                    <span className="font-mono text-slate-900 dark:text-white text-xs">{llmInfo.vision_model?.base_url || llmInfo.vision_base_url || '-'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-500">Max Tokens:</span>
                    <span className="font-mono">{llmInfo.vision_max_tokens || '-'}</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {llmInfo?.status === 'error' && (
            <div className="p-3 bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 rounded text-sm">
              ⚠️ LLM 服务不可用，请检查 LM Studio 或 OpenAI 服务是否运行。
            </div>
          )}
        </div>
      </Card>

      {/* Neo4j Connection Test */}
      <Card title="🕸️ Neo4j 连接">
        <div className="space-y-4">
          <div className="flex items-center gap-4">
            <Button variant="outline" onClick={testNeo4j} disabled={neo4jTesting}>
              {neo4jTesting ? <><Spinner size="sm" className="mr-2" />测试中...</> : '🔗 测试连接'}
            </Button>
            {neo4jStatus && (
              <Badge variant={neo4jStatus.neo4j_connected ? 'green' : 'red'}>
                {neo4jStatus.neo4j_connected ? '✅ 连接成功' : '❌ 连接失败'}
              </Badge>
            )}
          </div>
          {neo4jStatus && (
            <div className="text-sm text-slate-600 dark:text-slate-400 space-y-1">
              {neo4jStatus.total_entities != null && (
                <p>实体: {neo4jStatus.total_entities} | 关系: {neo4jStatus.total_relationships || 0}</p>
              )}
              {neo4jStatus.error && <p className="text-red-600">错误: {neo4jStatus.error}</p>}
            </div>
          )}
        </div>
      </Card>

      <Card title={t('settings.display')}>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('settings.theme')}
            </label>
            <select
              value={settings.theme}
              onChange={(e) => handleSettingChange('theme', e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 dark:bg-slate-700 dark:text-white"
            >
              <option value="light">{t('settings.theme.light')}</option>
              <option value="dark">{t('settings.theme.dark')}</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('settings.language')}
            </label>
            <select
              value={settings.language}
              onChange={(e) => handleSettingChange('language', e.target.value)}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 dark:bg-slate-700 dark:text-white"
            >
              <option value="en">English</option>
              <option value="zh">中文</option>
            </select>
          </div>
        </div>
      </Card>

      <Card title={t('settings.task_settings')}>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('settings.items_per_page')}
            </label>
            <input
              type="number"
              value={settings.itemsPerPage}
              onChange={(e) => handleSettingChange('itemsPerPage', parseInt(e.target.value))}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 dark:bg-slate-700 dark:text-white"
              min="5"
              max="100"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('settings.refresh_interval')}
            </label>
            <input
              type="number"
              value={settings.refreshInterval}
              onChange={(e) => handleSettingChange('refreshInterval', parseInt(e.target.value))}
              className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 dark:bg-slate-700 dark:text-white"
              min="1000"
              max="60000"
              step="1000"
            />
          </div>
          <label className="flex items-center">
            <input
              type="checkbox"
              checked={settings.autoRefresh}
              onChange={(e) => handleSettingChange('autoRefresh', e.target.checked)}
              className="rounded border-slate-300 text-primary-600 focus:ring-primary-500"
            />
            <span className="ml-2 text-sm text-slate-700 dark:text-slate-300">{t('settings.auto_refresh')}</span>
          </label>
        </div>
      </Card>

      <Card title={t('settings.actions')}>
        <div className="flex space-x-4">
          <Button variant="danger" onClick={handleReset}>
            {t('settings.reset')}
          </Button>
        </div>
      </Card>
    </div>
  );
};

export default Settings;

