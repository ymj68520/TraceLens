import React from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { updateSettings, resetSettings } from '../store/settingsSlice';
import Card from '../components/common/Card';
import Button from '../components/common/Button';

const Settings = () => {
  const dispatch = useDispatch();
  const settings = useSelector((state) => state.settings);

  const handleSettingChange = (key, value) => {
    dispatch(updateSettings({ [key]: value }));
  };

  const handleReset = () => {
    if (window.confirm('Are you sure you want to reset all settings to defaults?')) {
      dispatch(resetSettings());
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Settings</h1>
        <p className="mt-2 text-gray-600">Configure application settings</p>
      </div>

      <Card title="API Configuration">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              API URL
            </label>
            <input
              type="text"
              value={settings.apiUrl}
              onChange={(e) => handleSettingChange('apiUrl', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>
      </Card>

      <Card title="Display Settings">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Theme
            </label>
            <select
              value={settings.theme}
              onChange={(e) => handleSettingChange('theme', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Language
            </label>
            <select
              value={settings.language}
              onChange={(e) => handleSettingChange('language', e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="en">English</option>
              <option value="zh">中文</option>
            </select>
          </div>
        </div>
      </Card>

      <Card title="Task Settings">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Items Per Page
            </label>
            <input
              type="number"
              value={settings.itemsPerPage}
              onChange={(e) => handleSettingChange('itemsPerPage', parseInt(e.target.value))}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              min="5"
              max="100"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Refresh Interval (ms)
            </label>
            <input
              type="number"
              value={settings.refreshInterval}
              onChange={(e) => handleSettingChange('refreshInterval', parseInt(e.target.value))}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
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
            <span className="ml-2 text-sm text-gray-700">Auto-refresh running tasks</span>
          </label>
        </div>
      </Card>

      <Card title="Actions">
        <div className="flex space-x-4">
          <Button variant="danger" onClick={handleReset}>
            Reset to Defaults
          </Button>
        </div>
      </Card>
    </div>
  );
};

export default Settings;
