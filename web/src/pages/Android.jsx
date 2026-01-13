
import Card from '../components/common/Card';

const Android = () => {
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
          to view Android forensics data.
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
};

export default Android;
