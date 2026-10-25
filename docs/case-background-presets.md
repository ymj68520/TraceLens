# 案情背景预设 (Case Background Presets)

## 概述

案情背景（`case_description`）会原样进入 LLM 提示词，是文件筛选、单文件分析、事件簇研判和报告撰写的核心输入。此前每个入口都要求分析员从空白文本框开始手写，导致两件事反复发生：一是描述过于笼统（"查一下这个手机"），LLM 无法据此定位关键文件；二是同类案件每次写法不同，跨案件结果难以对比。

案情背景预设提供一组按业务场景预先写好的背景文本。用户在创建任务或案件时可以选择一个预设一键填入，也可以完全手动输入。预设只是起点——填入后仍可继续编辑，编辑后自动视为自定义背景。

## 功能特性

- **28 个预设，覆盖 6 大类主流取证场景**：涉网犯罪、入侵与恶意代码、数据与知识产权、人身与财产、企业与合规、专项检材
- **选择或自定义**：选中预设后文本进入正常输入框，可自由增删改；未选择或改动后显示"未使用预设，可手动输入"
- **推荐场景联动**（可选）：预设可携带推荐的过滤画像与取证平台，点击"套用到分析场景"一键写入，不点则保持用户当前选择
- **零后端改动**：预设完全在前端，最终仍以普通 `case_description` 字段提交，后端与提示词模板无变化
- **统一入口**：创建任务、新建多镜像案件、从已分析镜像组案、证据判定页的案情编辑、二次研判的本轮案情，全部使用同一个组件

## 预设清单

| 分组 | 预设 id | 名称 | 建议过滤画像 |
|------|---------|------|--------------|
| 涉网犯罪 | `telecom_fraud` | 电信网络诈骗 | `telecom_fraud` |
| 涉网犯罪 | `investment_scam_platform` | 虚假投资理财平台 | `诈骗平台服务器专项` |
| 涉网犯罪 | `gambling` | 网络赌博 | `诈骗平台服务器专项` / `telecom_fraud` |
| 涉网犯罪 | `drug_trafficking` | 毒品犯罪 | `telecom_fraud` |
| 涉网犯罪 | `online_porn` | 网络色情与偷拍 | `telecom_fraud` |
| 涉网犯罪 | `extortion` | 敲诈勒索与裸聊 | `telecom_fraud` |
| 入侵与恶意代码 | `malware_infection` | 病毒木马感染 | `virus_intrusion` |
| 入侵与恶意代码 | `ransomware` | 勒索软件攻击 | `virus_intrusion` |
| 入侵与恶意代码 | `apt_espionage` | APT / 定向攻击 | `virus_intrusion` |
| 入侵与恶意代码 | `web_attack` | 网站入侵与 WebShell | `virus_intrusion` |
| 数据与知识产权 | `data_breach` | 数据泄露 / 商业秘密窃取 | `data_breach` |
| 数据与知识产权 | `ip_infringement` | 侵犯知识产权 | `data_breach` |
| 数据与知识产权 | `illegal_operation` | 非法经营 / 传销 | `telecom_fraud` / `data_breach` |
| 人身与财产 | `homicide` | 命案 / 严重暴力犯罪 | `general_forensics` |
| 人身与财产 | `theft_burglary` | 盗窃 / 抢劫 | `general_forensics` |
| 人身与财产 | `missing_person` | 失踪人口 / 寻人 | `general_forensics` |
| 人身与财产 | `personal_dispute` | 婚姻家事 / 民事纠纷 | `general_forensics` |
| 人身与财产 | `corruption` | 职务犯罪 / 贿赂 | `data_breach` |
| 企业与合规 | `insider_threat` | 内部违规 / 员工舞弊 | `data_breach` |
| 企业与合规 | `compliance_audit` | 合规审计 / 等保检查 | `general_forensics` |
| 企业与合规 | `incident_response` | 安全事件应急响应 | `virus_intrusion` |
| 专项检材 | `android_mobile` | 手机取证（Android） | `telecom_fraud` |
| 专项检材 | `windows_workstation` | Windows 主机取证 | `general_forensics` |
| 专项检材 | `linux_server` | Linux 服务器取证 | `general_forensics` |
| 专项检材 | `memory_forensics` | 内存取证 | `virus_intrusion` |
| 专项检材 | `cloud_oss` | 云存储 / 对象存储取证 | `data_breach` |
| 专项检材 | `im_forensics` | 即时通讯专项 | `telecom_fraud` |
| 专项检材 | `unknown_triage` | 未知检材快速筛查 | `general_forensics` |

## 文案写法约定

每段预设按 LLM 提示词的读法组织，固定四段结构：

1. **案件性质与背景** — 让模型知道在查什么类型的案件
2. **检材与数据来源** — 设备类型、操作系统、涉及的应用
3. **需要重点查找的关键信息** — 可直接映射到文件名、字段、路径
4. **补充关注方向** — 已删除数据、加密应用、关联行为等

这样写是因为 `python_service/httpserver/prompts.py` 中的模板会把 `{case_description}` 直接嵌进"筛选原则""分析要求"之间，具体、可检索的描述比抽象概括更能稳定地提升筛选命中率。

## 代码结构

| 文件 | 说明 |
|------|------|
| `web/src/config/caseBackgroundPresets.js` | 预设数据、分组定义、`getPresetById` / `matchPresetId` / `presetsByGroup` 工具 |
| `web/src/components/tasks/CaseBackgroundField.jsx` | `CaseBackgroundPresetPicker`（纯选择器）与 `CaseBackgroundField`（标签 + 选择器 + 文本框） |
| `web/src/components/tasks/CreateTaskModal.jsx` | 创建任务：预设 + "套用到分析场景"联动过滤画像/平台 |
| `web/src/components/tasks/CreateCaseModal.jsx` | 新建多镜像案件 |
| `web/src/components/tasks/ComposeCaseModal.jsx` | 从已分析镜像组案 |
| `web/src/pages/AnalysisCenter.jsx` | 证据判定页的案情背景编辑 |
| `web/src/components/reports/GenerateReportPanel.jsx` | 二次研判的本轮案情描述 |

## 扩展指南

### 新增一个预设

在 `CASE_BACKGROUND_PRESETS` 中追加一条即可，界面分组和卡片列表会自动生效：

```js
{
  id: 'new_scenario',          // 稳定标识，不要随文案改动
  label: '新场景名称',
  icon: '🧩',
  group: 'fraud',              // 必须是 PRESET_GROUPS 中已有的 key
  summary: '一句话说明，展示在卡片上',
  filterProfiles: ['telecom_fraud'],  // 可选，必须是已存在的画像名
  scenarios: ['android'],             // 可选，android/windows/linux/server_cloud
  background: '完整的案情背景正文……',
}
```

### 新增一个分组

1. 在 `PRESET_GROUPS` 中加入 `{ key, label }`
2. 给新预设设置 `group` 为该 key
3. `presetsByGroup()` 会自动过滤掉没有预设的空分组

### 匹配规则

`matchPresetId(text)` 用**全文精确匹配**（仅 trim）判断当前文本属于哪个预设。用户一旦修改文本，就不再匹配任何预设，界面回到"自定义"状态。这意味着：

- 调整某条预设的 `background` 文案，等同于让已保存的旧文本变成"自定义"，不会误标为预设
- 两个预设的 `background` 必须唯一，测试 `presets are unique` 会守住这条约束

## 测试

```bash
cd web
npx vitest run src/config/caseBackgroundPresets.test.js \
                src/components/tasks/CaseBackgroundField.test.jsx \
                src/components/tasks/CreateTaskModal.preset.test.jsx
```

覆盖内容：

- 每条预设的字段完整性、分组合法性、正文长度与占位词检查
- 主流场景（诈骗、勒索、数据泄露、命案、Android/Windows/Linux/内存/云）必须存在
- 预设正文唯一性（保证 `matchPresetId` 无歧义）
- 推荐的过滤画像与平台名必须真实存在
- 选择预设写入全文、改动后回退自定义、分组切换、禁用态、面板收起
- 创建任务时预设文本原样进入 `case_description`；套用推荐后 `filter_profile` 同步变更；手动输入不受影响

## 设计取舍

**为什么不做后端配置接口？** 预设是纯展示层的便捷输入，不参与业务判断。放在前端可以随打包一起版本化，避免多一个需要鉴权、缓存和迁移的接口。若后续需要运营侧动态调整，再把 `CASE_BACKGROUND_PRESETS` 换成 `GET /api/case-background-presets` 即可，组件契约不变。

**为什么不用 `<select>`？** 28 条带说明的预设用下拉框无法展示摘要，且会打乱现有测试对表单控件顺序的假设（多个测试用 `getAllByRole('combobox')[0]` 取数据源下拉框）。卡片式面板不影响表单控件顺序。
