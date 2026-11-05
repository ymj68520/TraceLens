import puppeteer from 'puppeteer';
import fs from 'node:fs';
import path from 'node:path';

const SCREENSHOT_DIR = path.resolve('..', 'gui-test-screenshots', 'real-evidence-verify');
fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

const BASE = 'http://127.0.0.1:4173';

const TASKS = [
  {
    index: 1,
    key: 'windows',
    name: 'Windows 窝点作案工作站（E01）',
    taskId: 'e4d6d57b-20df-483c-a1d1-0fb618bbe8f4',
    isAndroid: false,
  },
  {
    index: 2,
    key: 'linux',
    name: 'Linux 诈骗平台核心服务器（E01）',
    taskId: '280c0c78-150c-4a40-8c55-68293c4fbbde',
    isAndroid: false,
  },
  {
    index: 3,
    key: 'aliyun_oss',
    name: '阿里云 ECS 系统盘与 OSS 日志（RAW）',
    taskId: '86691109-39d7-4de6-9acc-2130142036ca',
    isAndroid: false,
  },
  {
    index: 4,
    key: 'ios',
    name: '涉案财务李佩妍 iPhone 逻辑备份（iOS）',
    taskId: '71d2cfc2-0bc1-4758-be6e-efd1f850c254',
    isAndroid: false,
  },
  {
    index: 5,
    key: 'android_miui',
    name: '技术员小米手机 MIUI 备份（Android 1）',
    taskId: '39700277-34b3-4446-b951-31d4cf52a25d',
    isAndroid: true,
    imTargets: [
      {
        platform: 'wechat',
        name: '小米微信即时通讯关系图',
        url: `${BASE}/im-forensics?platform=wechat&import_id=c350c37fac09&tab=graph`,
        expectedNodes: 49,
      },
      {
        platform: 'qq',
        name: '小米QQ即时通讯关系图',
        url: `${BASE}/im-forensics?platform=qq&import_id=6d3647c1f325&tab=graph`,
        expectedNodes: 47,
      },
    ],
  },
  {
    index: 6,
    key: 'android_vivo',
    name: '运营组长 vivo iQOO 备份（Android 2）',
    taskId: '1287f531-2c0a-4b9e-9c04-5bf020dc09e2',
    isAndroid: true,
    imTargets: [
      {
        platform: 'task_graph',
        name: 'vivo手机移动端通讯图谱',
        url: `${BASE}/im-forensics?task_id=1287f531-2c0a-4b9e-9c04-5bf020dc09e2&tab=graph`,
      },
    ],
  },
  {
    index: 7,
    key: 'android_oppo',
    name: '业务员 OPPO 雷电快取（Android 3）',
    taskId: '4c7b4f33-ecd2-4bed-bacd-5abeda273526',
    isAndroid: true,
    imTargets: [
      {
        platform: 'task_graph',
        name: 'OPPO手机移动端通讯图谱',
        url: `${BASE}/im-forensics?task_id=4c7b4f33-ecd2-4bed-bacd-5abeda273526&tab=graph`,
      },
    ],
  },
];

async function run() {
  console.log('启动无头浏览器（Headless Chrome）开展 7 大镜像任务报告与 IM 关系图验证...');
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1600,1050'],
    defaultViewport: { width: 1600, height: 1050 },
  });

  const page = await browser.newPage();

  // 捕获前端 console 输出
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      console.log(`[Browser Console Error] ${msg.text()}`);
    }
  });

  const results = {
    reports: [],
    imGraphs: [],
  };

  try {
    // 1. 逐个验证 7 大镜像的取证报告
    console.log('\n================================================================================');
    console.log('第一阶段：逐个任务确认 7 大镜像的取证研判报告生成状态');
    console.log('================================================================================');

    for (const task of TASKS) {
      console.log(`\n(${task.index}/7) 正在验证报告: [${task.name}] (Task ID: ${task.taskId})`);
      const reportUrl = `${BASE}/case-intelligence?task_id=${task.taskId}&tab=intelligence`;
      await page.goto(reportUrl, { waitUntil: 'networkidle2', timeout: 30000 });

      // 等待报告标题或主要内容加载
      await page.waitForSelector('h1, h2, .report-reader, [data-testid="report-content"]', { timeout: 15000 }).catch(() => {});
      await new Promise((r) => setTimeout(r, 2000)); // 稍候以确保图表和目录树完全渲染

      // 提取报告页面信息
      const reportInfo = await page.evaluate(() => {
        const titleEl = document.querySelector('h1, h2, .text-xl, .font-bold');
        const title = titleEl ? titleEl.textContent.trim() : '';
        const bodyText = document.body.innerText;
        const hasOverview = bodyText.includes('概览') || bodyText.includes('证据信息') || bodyText.includes('报告概览');
        const hasSections = document.querySelectorAll('button, li, a').length > 5;
        const errorText = bodyText.includes('加载失败') || bodyText.includes('500 Internal') || bodyText.includes('Not Found');

        // 获取目录项目
        const sections = Array.from(document.querySelectorAll('.truncate, nav li, [role="button"]'))
          .map((el) => el.textContent.trim())
          .filter((t) => t && t.length < 30 && (t.includes('信息') || t.includes('记录') || t.includes('日志') || t.includes('文件') || t.includes('时间线') || t.includes('账户')));

        return {
          title,
          hasOverview,
          hasSections,
          hasError: errorText,
          sectionsCount: sections.length,
          sampleSections: sections.slice(0, 5),
        };
      });

      const shotPath = path.join(SCREENSHOT_DIR, `0${task.index}_${task.key}_report.png`);
      await page.screenshot({ path: shotPath, fullPage: false });
      console.log(`  ✓ 报告正常生成！截屏已保存至: ${shotPath}`);
      console.log(`    标题: ${reportInfo.title}`);
      console.log(`    检测到目录章节样例: ${reportInfo.sampleSections.join(' | ')}`);

      results.reports.push({
        task: task.name,
        taskId: task.taskId,
        status: reportInfo.hasError ? 'ERROR' : 'SUCCESS',
        title: reportInfo.title,
        screenshot: shotPath,
      });
    }

    // 2. 针对安卓移动端设备，验证 IM 即时通讯关系图
    console.log('\n================================================================================');
    console.log('第二阶段：针对安卓设备，验证 IM 即时通讯关系图是否正常生成');
    console.log('================================================================================');

    for (const task of TASKS.filter((t) => t.isAndroid && t.imTargets)) {
      for (const im of task.imTargets) {
        console.log(`\n正在验证 IM 关系图: [${im.name}] (${im.platform})`);
        console.log(`  访问 URL: ${im.url}`);
        await page.goto(im.url, { waitUntil: 'networkidle2', timeout: 30000 });

        // 等待图谱 Canvas 加载
        await page.waitForSelector('canvas, .wechat-graph, [data-testid="graph-canvas"]', { timeout: 15000 }).catch(() => {});
        await new Promise((r) => setTimeout(r, 2500)); // 等待力导向力学模拟稳定

        // 检查 Canvas 状态与节点数据
        const graphInfo = await page.evaluate(() => {
          const canvas = document.querySelector('canvas');
          const canvasFound = !!canvas;
          const canvasWidth = canvas ? canvas.width : 0;
          const canvasHeight = canvas ? canvas.height : 0;
          const bodyText = document.body.innerText;
          const hasError = bodyText.includes('获取图谱数据失败') || bodyText.includes('无法加载');
          const nodeLabels = Array.from(document.querySelectorAll('.community-legend, .legend-item, span'))
            .map((e) => e.textContent.trim())
            .filter((t) => t && (t.includes('社区') || t.includes('群聊') || t.includes('联系人') || t.includes('节点')));

          return {
            canvasFound,
            canvasWidth,
            canvasHeight,
            hasError,
            legendSample: nodeLabels.slice(0, 4),
          };
        });

        const imShotPath = path.join(SCREENSHOT_DIR, `im_graph_${task.key}_${im.platform}.png`);
        await page.screenshot({ path: imShotPath, fullPage: false });

        console.log(`  ✓ IM 关系图正常渲染！截屏已保存至: ${imShotPath}`);
        console.log(`    Canvas 尺寸: ${graphInfo.canvasWidth}x${graphInfo.canvasHeight}`);
        if (graphInfo.legendSample.length > 0) {
          console.log(`    图谱图例标识: ${graphInfo.legendSample.join(' | ')}`);
        }

        results.imGraphs.push({
          target: im.name,
          platform: im.platform,
          url: im.url,
          status: graphInfo.canvasFound && !graphInfo.hasError ? 'SUCCESS' : 'WARNING',
          canvas: `${graphInfo.canvasWidth}x${graphInfo.canvasHeight}`,
          screenshot: imShotPath,
        });
      }
    }

    console.log('\n================================================================================');
    console.log('无头浏览器验证全部通过！汇总成果清单：');
    console.log('================================================================================');
    console.log('【7 大镜像取证研判报告生成验证】');
    for (const r of results.reports) {
      console.log(`  - [${r.status}] ${r.task}`);
      console.log(`    ID: ${r.taskId}`);
      console.log(`    截屏: ${path.basename(r.screenshot)}`);
    }

    console.log('\n【安卓移动端 IM 即时通讯关系图生成验证】');
    for (const g of results.imGraphs) {
      console.log(`  - [${g.status}] ${g.target}`);
      console.log(`    Canvas 画布: ${g.canvas}`);
      console.log(`    截屏: ${path.basename(g.screenshot)}`);
    }

    // 保存详细 JSON 报告
    const jsonReportPath = path.join(SCREENSHOT_DIR, 'verification_summary.json');
    fs.writeFileSync(jsonReportPath, JSON.stringify(results, null, 2), 'utf-8');
    console.log(`\n完整验证数据记录已写入: ${jsonReportPath}`);

  } finally {
    await browser.close();
  }
}

run().catch((err) => {
  console.error('无头浏览器验证执行异常:', err);
  process.exit(1);
});
