
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import Card from '../components/common/Card';
import Badge from '../components/common/Badge';
import Spinner from '../components/common/Spinner';
import {
  getAndroidCommunication,
  getAndroidAppUsage,
  getAndroidDeviceInfo,
  getAndroidMediaAnalysis,
} from '../services/forensicsService';

const Android = () => {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const { tasks } = useSelector((state) => state.tasks);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('communication');

  // Data states
  const [communicationData, setCommunicationData] = useState(null);
  const [appUsageData, setAppUsageData] = useState(null);
  const [deviceInfo, setDeviceInfo] = useState(null);
  const [mediaData, setMediaData] = useState(null);

  const currentTask = tasks.find((t) => t.id === taskId);

  useEffect(() => {
    if (!taskId) return;

    const fetchData = async () => {
      setLoading(true);
      setError(null);

      try {
        // Fetch all Android data in parallel
        const [commData, appData, devData, medData] = await Promise.allSettled([
          getAndroidCommunication(taskId),
          getAndroidAppUsage(taskId),
          getAndroidDeviceInfo(taskId),
          getAndroidMediaAnalysis(taskId),
        ]);

        if (commData.status === 'fulfilled') setCommunicationData(commData.value);
        if (appData.status === 'fulfilled') setAppUsageData(appData.value);
        if (devData.status === 'fulfilled') setDeviceInfo(devData.value);
        if (medData.status === 'fulfilled') setMediaData(medData.value);

        // Check if any data was fetched
        const hasAnyData = [commData, appData, devData, medData].some(
          (r) => r.status === 'fulfilled' && r.value
        );

        if (!hasAnyData) {
          setError('No Android data found for this task. Make sure Android analysis was enabled.');
        }
      } catch (err) {
        console.error('Failed to fetch Android data:', err);
        setError(err.message || 'Failed to load Android forensics data');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [taskId]);

  // Format date
  const formatDate = (timestamp) => {
    if (!timestamp) return '-';
    try {
      return new Date(timestamp * 1000).toLocaleString();
    } catch {
      return timestamp;
    }
  };

  if (!taskId) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Android Forensics</h1>
          <p className="mt-2 text-gray-600">Analyze Android device artifacts</p>
        </div>

        <Card title="Select a Task">
          <p className="text-gray-500">
            Select a completed task with Android analysis enabled from the{' '}
            <a href="/tasks" className="text-blue-600 hover:text-blue-800">
              Tasks page
            </a>{' '}
            or use the task selector in the top bar to view Android forensics data.
          </p>
        </Card>

        <Card title="Android Analysis Features">
          <ul className="space-y-2 text-gray-600">
            <li>• SMS and MMS messages</li>
            <li>• Contacts analysis</li>
            <li>• Call logs</li>
            <li>• App usage statistics</li>
            <li>• Device information</li>
            <li>• Media file analysis</li>
          </ul>
        </Card>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Android Forensics</h1>
          <p className="mt-2 text-gray-600">Task: {currentTask?.image_path || taskId}</p>
        </div>
        <Card>
          <div className="flex items-center justify-center h-64">
            <Spinner size="lg" />
            <span className="ml-4 text-gray-600">Loading Android data...</span>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Android Forensics</h1>
        <p className="mt-2 text-gray-600">Task: {currentTask?.image_path || taskId}</p>
        {currentTask && (
          <div className="mt-2">
            <Badge variant="blue">{currentTask.status}</Badge>
            {currentTask.android_analyze && (
              <Badge variant="green" className="ml-2">Android Analysis</Badge>
            )}
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <Card title="Error">
          <div className="p-4 bg-red-50 border border-red-200 rounded-md">
            <p className="text-red-800">{error}</p>
          </div>
        </Card>
      )}

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-8" aria-label="Tabs">
          {[
            { id: 'communication', label: '📱 Communication', hasData: communicationData },
            { id: 'apps', label: '📦 Apps', hasData: appUsageData },
            { id: 'device', label: '📋 Device Info', hasData: deviceInfo },
            { id: 'media', label: '🖼️ Media', hasData: mediaData },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`${activeTab === tab.id
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
            >
              {tab.label}
              {!tab.hasData && <span className="ml-1 text-xs text-gray-400">(No data)</span>}
            </button>
          ))}
        </nav>
      </div>

      {/* Communication Tab */}
      {activeTab === 'communication' && (
        <Card title="📱 Communication Summary">
          {communicationData ? (
            <div className="space-y-6">
              {/* SMS Messages */}
              {communicationData.sms && communicationData.sms.length > 0 && (
                <div>
                  <h4 className="font-medium text-gray-900 mb-3">SMS Messages ({communicationData.sms.length})</h4>
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Address</th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Message</th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {communicationData.sms.slice(0, 50).map((sms, idx) => (
                          <tr key={idx} className="hover:bg-gray-50">
                            <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                              {formatDate(sms.date)}
                            </td>
                            <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900">
                              {sms.address}
                            </td>
                            <td className="px-4 py-3 whitespace-nowrap">
                              <Badge variant={sms.type === 'received' ? 'green' : 'blue'}>
                                {sms.type || 'unknown'}
                              </Badge>
                            </td>
                            <td className="px-4 py-3 text-sm text-gray-600 max-w-md truncate">
                              {sms.body}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Call Logs */}
              {communicationData.calls && communicationData.calls.length > 0 && (
                <div>
                  <h4 className="font-medium text-gray-900 mb-3">Call Logs ({communicationData.calls.length})</h4>
                  <div className="overflow-x-auto">
                    <table className="min-w-full divide-y divide-gray-200">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Number</th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                          <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Duration</th>
                        </tr>
                      </thead>
                      <tbody className="bg-white divide-y divide-gray-200">
                        {communicationData.calls.slice(0, 50).map((call, idx) => (
                          <tr key={idx} className="hover:bg-gray-50">
                            <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                              {formatDate(call.date)}
                            </td>
                            <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-900">
                              {call.number}
                            </td>
                            <td className="px-4 py-3 whitespace-nowrap">
                              <Badge variant={
                                call.type === 'incoming' ? 'green' :
                                  call.type === 'outgoing' ? 'blue' :
                                    call.type === 'missed' ? 'red' : 'gray'
                              }>
                                {call.type || 'unknown'}
                              </Badge>
                            </td>
                            <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                              {call.duration ? `${Math.floor(call.duration / 60)}m ${call.duration % 60}s` : '-'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Contacts */}
              {communicationData.contacts && communicationData.contacts.length > 0 && (
                <div>
                  <h4 className="font-medium text-gray-900 mb-3">Contacts ({communicationData.contacts.length})</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {communicationData.contacts.slice(0, 30).map((contact, idx) => (
                      <div key={idx} className="p-3 bg-gray-50 rounded-lg">
                        <p className="font-medium text-gray-900">{contact.name || 'Unknown'}</p>
                        <p className="text-sm text-gray-600">{contact.phone || contact.number}</p>
                        {contact.email && <p className="text-sm text-gray-500">{contact.email}</p>}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {!communicationData.sms?.length && !communicationData.calls?.length && !communicationData.contacts?.length && (
                <p className="text-center py-8 text-gray-500">No communication data found</p>
              )}
            </div>
          ) : (
            <p className="text-center py-8 text-gray-500">No communication data available</p>
          )}
        </Card>
      )}

      {/* Apps Tab */}
      {activeTab === 'apps' && (
        <Card title="📦 Application Usage">
          {appUsageData && appUsageData.apps && appUsageData.apps.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">App Name</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Package</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Version</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last Used</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {appUsageData.apps.slice(0, 100).map((app, idx) => (
                    <tr key={idx} className="hover:bg-gray-50">
                      <td className="px-4 py-3 whitespace-nowrap text-sm font-medium text-gray-900">
                        {app.name || app.label || 'Unknown'}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-600 font-mono">
                        {app.package || app.package_name}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                        {app.version || '-'}
                      </td>
                      <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                        {app.last_used ? formatDate(app.last_used) : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-center py-8 text-gray-500">No application data available</p>
          )}

          {/* App Database Files Section */}
          {appUsageData && appUsageData.app_database_files && appUsageData.app_database_files.length > 0 && (
            <div className="mt-8">
              <h4 className="font-medium text-gray-900 mb-3">🗄️ App Database Files ({appUsageData.app_database_files.length})</h4>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">File Name</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Full Path</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Package</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Size</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {appUsageData.app_database_files.slice(0, 100).map((dbFile, idx) => (
                      <tr key={idx} className="hover:bg-gray-50">
                        <td className="px-4 py-3 whitespace-nowrap text-sm font-medium text-gray-900">
                          {dbFile.file_name}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600 font-mono max-w-md truncate" title={dbFile.file_path}>
                          {dbFile.file_path}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600 font-mono">
                          {dbFile.package_name}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                          {dbFile.file_size ? `${(dbFile.file_size / 1024).toFixed(2)} KB` : '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </Card>
      )}

      {/* Device Info Tab */}
      {activeTab === 'device' && (
        <Card title="📋 Device Information">
          {deviceInfo ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {Object.entries(deviceInfo).map(([key, value]) => (
                <div key={key} className="p-4 bg-gray-50 rounded-lg">
                  <p className="text-sm font-medium text-gray-500 capitalize">
                    {key.replace(/_/g, ' ')}
                  </p>
                  <p className="mt-1 text-sm text-gray-900">
                    {typeof value === 'object' ? JSON.stringify(value) : String(value || '-')}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-center py-8 text-gray-500">No device information available</p>
          )}
        </Card>
      )}

      {/* Media Tab */}
      {activeTab === 'media' && (
        <Card title="🖼️ Media Analysis">
          {mediaData && mediaData.media && mediaData.media.length > 0 ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <div className="p-4 bg-blue-50 rounded-lg text-center">
                  <p className="text-2xl font-bold text-blue-900">
                    {mediaData.media.filter(m => m.type === 'image').length}
                  </p>
                  <p className="text-sm text-blue-600">Images</p>
                </div>
                <div className="p-4 bg-green-50 rounded-lg text-center">
                  <p className="text-2xl font-bold text-green-900">
                    {mediaData.media.filter(m => m.type === 'video').length}
                  </p>
                  <p className="text-sm text-green-600">Videos</p>
                </div>
                <div className="p-4 bg-purple-50 rounded-lg text-center">
                  <p className="text-2xl font-bold text-purple-900">
                    {mediaData.media.filter(m => m.type === 'audio').length}
                  </p>
                  <p className="text-sm text-purple-600">Audio</p>
                </div>
                <div className="p-4 bg-gray-50 rounded-lg text-center">
                  <p className="text-2xl font-bold text-gray-900">{mediaData.media.length}</p>
                  <p className="text-sm text-gray-600">Total</p>
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">File</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Size</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {mediaData.media.slice(0, 50).map((media, idx) => (
                      <tr key={idx} className="hover:bg-gray-50">
                        <td className="px-4 py-3 text-sm text-gray-900 max-w-md truncate">
                          {media.path || media.name}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <Badge variant={
                            media.type === 'image' ? 'blue' :
                              media.type === 'video' ? 'green' :
                                media.type === 'audio' ? 'purple' : 'gray'
                          }>
                            {media.type || 'unknown'}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                          {media.size ? `${(media.size / 1024 / 1024).toFixed(2)} MB` : '-'}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap text-sm text-gray-600">
                          {media.date ? formatDate(media.date) : '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <p className="text-center py-8 text-gray-500">No media data available</p>
          )}
        </Card>
      )}
    </div>
  );
};

export default Android;
