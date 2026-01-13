# Digital Forensics Tool - Web Interface

React前端界面用于数字取证分析工具。

## 技术栈

- **React 18** - UI框架
- **React Router 6** - 客户端路由
- **Redux Toolkit** - 状态管理
- **Tailwind CSS** - CSS框架
- **D3.js** - 数据可视化
- **Axios** - HTTP客户端
- **Vite** - 构建工具

## 功能特性

### 核心功能
- ✅ **任务管理** - 创建、监控、取消分析任务
- ✅ **实时进度跟踪** - 自适应轮询策略，实时显示任务进度
- ✅ **仪表板** - 系统概览、任务统计、快速操作
- ✅ **时间线分析** - 文件系统事件时间线可视化
- ✅ **文件分析** - 浏览和分析提取的文件
- ✅ **Android取证** - SMS、联系人、通话记录等
- ✅ **全文搜索** - 基于Xapian的文件内容搜索
- ✅ **统计分析** - 文件分布、活动模式、删除文件分析

### 页面结构
- **Dashboard** (`/dashboard`) - 主仪表板
- **Tasks** (`/tasks`) - 任务管理页面
- **Timeline** (`/timeline`) - 时间线分析页面
- **Files** (`/files`) - 文件分析页面
- **Android** (`/android`) - Android取证页面
- **Search** (`/search`) - 全文搜索页面
- **Statistics** (`/statistics`) - 统计分析页面
- **Settings** (`/settings`) - 设置页面

## 开发指南

### 前置要求

- Node.js 18+
- npm 9+

### 安装依赖

```bash
cd web
npm install
```

### 开发模式

```bash
# 启动Vite开发服务器（支持热重载）
npm run dev

# 前端运行在 http://localhost:3000
# API请求代理到后端 http://localhost:8080
```

### 生产构建

```bash
# 构建生产版本
npm run build

# 预览构建结果
npm run preview
```

### 代码质量

```bash
# ESLint检查
npm run lint

# Prettier格式化
npm run format
```

## 项目结构

```
web/
├── public/                    # 静态资源
│   └── index.html
├── src/
│   ├── components/            # React组件
│   │   ├── common/           # 通用组件
│   │   ├── Layout/           # 布局组件
│   │   ├── task/             # 任务相关组件
│   │   ├── timeline/         # 时间线可视化
│   │   ├── files/            # 文件分析组件
│   │   ├── android/          # Android取证组件
│   │   ├── search/           # 搜索组件
│   │   └── visualization/    # D3.js可视化组件
│   ├── pages/                # 页面级组件
│   ├── hooks/                # 自定义React Hooks
│   ├── services/             # API服务层
│   ├── store/                # Redux store
│   ├── utils/                # 工具函数
│   ├── styles/               # 全局样式
│   ├── App.jsx               # 根组件
│   ├── index.jsx             # 入口文件
│   └── routes.jsx            # 路由配置
├── package.json              # 项目配置
├── vite.config.js           # Vite配置
├── tailwind.config.js       # Tailwind配置
└── README.md                # 本文件
```

## 集成构建

前端已集成到主CMake构建系统：

```bash
# 从项目根目录构建
cd ForensicsProject
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j$(nproc)

# 运行服务器
./forensic_analyzer --http-server 8080

# 访问Web界面
open http://localhost:8080
```

### CMake选项

- `BUILD_WEB_FRONTEND=ON` - 构建前端（默认）
- `BUILD_WEB_FRONTEND=OFF` - 跳过前端构建

## 配置

### 环境变量

创建 `.env.local` 文件用于本地开发：

```bash
# API基础URL
VITE_API_BASE_URL=http://localhost:8080

# 应用标题
VITE_APP_TITLE=Digital Forensics Tool

# WebSocket支持（未来）
VITE_ENABLE_WEBSOCKET=false
```

### 设置

应用设置保存在浏览器的localStorage中，包括：
- API URL
- 主题（浅色/深色）
- 语言
- 每页项目数
- 刷新间隔
- 自动刷新开关

## API集成

前端通过以下服务与后端通信：

### 任务服务 (taskService.js)
```javascript
import * as taskService from './services/taskService';

// 创建任务
await taskService.createTask({
  image_path: '/path/to/image.dd',
  priority: 'normal',
  android_analyze: false,
  xfs_mode: 'auto'
});

// 获取任务列表
const tasks = await taskService.listTasks({ status: 'running' });

// 取消任务
await taskService.cancelTask(taskId, 'User cancelled');
```

### 取证服务 (forensicsService.js)
```javascript
import * as forensicsService from './services/forensicsService';

// 获取时间线
const timeline = await forensicsService.getComprehensiveTimeline(taskId);

// 获取文件分布
const distribution = await forensicsService.getFileDistribution(taskId);
```

## 实时更新

使用自定义Hook `useTaskPolling` 实现任务进度实时更新：

```javascript
import { useTaskPolling } from './hooks/useTaskPolling';

function TaskMonitor({ taskId }) {
  useTaskPolling(taskId, {
    interval: 2000,      // 轮询间隔（毫秒）
    enabled: true,       // 启用轮询
    onComplete: (result) => {
      console.log('Task completed:', result);
    }
  });

  return <div>Monitoring task...</div>;
}
```

自适应轮询策略：
- `initializing`, `finalizing`: 5秒
- `image_analysis`, `event_extraction`: 10秒
- `file_classification`, `llm_analysis`, `android_analysis`: 3秒

## 可视化组件

### D3.js图表

```javascript
import PieChart from './components/visualization/PieChart';
import TimelineChart from './components/visualization/TimelineChart';
import Heatmap from './components/visualization/Heatmap';

// 饼图 - 文件分布
<PieChart data={fileData} width={400} height={400} title="File Distribution" />

// 时间线图表
<TimelineChart data={timelineData} width={800} height={400} />

// 热力图 - 活动模式
<Heatmap data={activityData} width={800} height={400} />
```

## 部署

### 生产部署

1. 构建前端和后端：
```bash
cmake .. -DCMAKE_BUILD_TYPE=Release -DBUILD_WEB_FRONTEND=ON
cmake --build . -j$(nproc)
```

2. 前端文件位于 `build/web/dist/`

3. C++服务器会自动提供静态文件服务

### Docker部署（可选）

```dockerfile
FROM node:18 AS frontend-builder
WORKDIR /app
COPY web/package*.json ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM gcc:11 AS backend-builder
WORKDIR /app
COPY . .
COPY --from=frontend-builder /app/dist ./web
RUN mkdir build && cd build && cmake .. && make -j$(nproc)

FROM ubuntu:22.04
# ... 安装运行时依赖 ...
COPY --from=backend-builder /app/build/forensic_analyzer /usr/local/bin/
COPY --from=backend-builder /app/build/web /var/www/html
CMD ["forensic_analyzer", "--http-server", "8080"]
```

## 性能优化

- ✅ **代码分割** - React、D3、Redux分别打包
- ✅ **懒加载** - 路由级别的代码分割
- ✅ **缓存策略** - 静态资源缓存1年
- ✅ **Gzip压缩** - 通过C++服务器启用
- ✅ **Tree Shaking** - Vite自动优化

## 浏览器支持

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+

## 故障排查

### 前端无法加载

1. 检查前端是否已构建：
```bash
ls build/web/dist/index.html
```

2. 重新构建前端：
```bash
cmake --build . --target web_frontend
```

### API请求失败

1. 检查后端服务器是否运行：
```bash
curl http://localhost:8080/api/system/health
```

2. 检查CORS配置（开发环境由Vite代理处理）

### 任务进度不更新

1. 检查浏览器控制台是否有错误
2. 确认轮询设置：设置 → 刷新间隔
3. 手动刷新任务列表

## 未来增强

- [ ] WebSocket支持（替代轮询）
- [ ] 用户认证和授权
- [ ] 实时通知系统
- [ ] 更多D3.js可视化图表
- [ ] 导出功能（PDF、Excel）
- [ ] 多语言支持（i18n）
- [ ] 暗色主题
- [ ] PWA支持

## 贡献

欢迎贡献！请遵循以下步骤：

1. Fork本仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启Pull Request

## 许可证

本项目采用MIT许可证 - 详见LICENSE文件

## 联系方式

- 项目主页: [GitHub Repository]
- 问题反馈: [Issues]
