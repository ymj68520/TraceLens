import { useSelector, useDispatch } from 'react-redux';
import { updateSettings, resetSettings } from '../store/settingsSlice';
import { useTranslation } from '../hooks/useTranslation';
import Card from '../components/common/Card';
import Button from '../components/common/Button';

const Settings = () => {
  const dispatch = useDispatch();
  const settings = useSelector((state) => state.settings);
  const { t } = useTranslation();

  const handleSettingChange = (key, value) => {
    dispatch(updateSettings({ [key]: value }));
  };

  const handleReset = () => {
    if (window.confirm(t('settings.reset_confirm'))) {
      dispatch(resetSettings());
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100">{t('settings.title')}</h1>
        <p className="mt-2 text-gray-600 dark:text-gray-400">{t('settings.subtitle')}</p>
      </div>

      <Card title={t('settings.api_config')}>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              {t('settings.api_url')}
            </label>
            <input
              type="text"
              value={settings.apiUrl}
              onChange={(e) => handleSettingChange('apiUrl', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white"
            />
          </div>
        </div>
      </Card>

      <Card title={t('settings.display')}>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              {t('settings.theme')}
            </label>
            <select
              value={settings.theme}
              onChange={(e) => handleSettingChange('theme', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white"
            >
              <option value="light">{t('settings.theme.light')}</option>
              <option value="dark">{t('settings.theme.dark')}</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              {t('settings.language')}
            </label>
            <select
              value={settings.language}
              onChange={(e) => handleSettingChange('language', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white"
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
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              {t('settings.items_per_page')}
            </label>
            <input
              type="number"
              value={settings.itemsPerPage}
              onChange={(e) => handleSettingChange('itemsPerPage', parseInt(e.target.value))}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white"
              min="5"
              max="100"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              {t('settings.refresh_interval')}
            </label>
            <input
              type="number"
              value={settings.refreshInterval}
              onChange={(e) => handleSettingChange('refreshInterval', parseInt(e.target.value))}
              className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white"
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
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <span className="ml-2 text-sm text-gray-700 dark:text-gray-300">{t('settings.auto_refresh')}</span>
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
