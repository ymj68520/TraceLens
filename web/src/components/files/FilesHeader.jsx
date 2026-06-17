// FilesHeader.jsx
// Page header for the Files page: title, task name, and status badges.

import { motion } from 'framer-motion';
import Badge from '../common/Badge';

const FilesHeader = ({ currentTask, taskId, llmStatus, graphitiStatus }) => {
  const llmAvailable = llmStatus?.status === 'healthy' || llmStatus?.status === 'available';

  return (
    <div>
      <motion.h1
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="text-3xl font-bold text-slate-900 dark:text-white"
      >
        文件分析
      </motion.h1>
      <p className="mt-2 text-slate-600 dark:text-slate-300">任务: {currentTask?.image_path || taskId}</p>
      {currentTask && (
        <div className="mt-2 flex gap-2">
          <Badge variant="blue">{currentTask.status}</Badge>
          {llmAvailable && <Badge variant="green">LLM 可用</Badge>}
          {graphitiStatus?.neo4j_connected && <Badge variant="purple">Graphiti 已连接</Badge>}
        </div>
      )}
    </div>
  );
};

export default FilesHeader;
