
import Card from '../components/common/Card';

import { useSearchParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import Badge from '../components/common/Badge';

const Android = () => {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const { tasks } = useSelector((state) => state.tasks);

  const currentTask = tasks.find((t) => t.id === taskId);

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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Android Forensics</h1>
        <p className="mt-2 text-gray-600">Task: {currentTask?.image_path || taskId}</p>
        {currentTask && (
          <div className="mt-2">
            <Badge variant="blue">{currentTask.status}</Badge>
            {currentTask.android_analyze && <Badge variant="green" className="ml-2">Android Analysis</Badge>}
          </div>
        )}
      </div>

      <Card title="Android Artifacts">
        {currentTask?.android_analyze ? (
          <div className="text-center py-12 text-gray-500">
            <p>Android analysis data visualization coming soon...</p>
            <p className="text-sm mt-2">Data extracted to: {currentTask.db_output_dir || "default directory"}</p>
          </div>
        ) : (
          <div className="text-center py-12 text-gray-500">
            <p>Android analysis was not enabled for this task.</p>
          </div>
        )}
      </Card>
    </div>
  );
};

export default Android;
