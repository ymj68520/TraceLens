export const PEOPLE_LEVELS = {
  core: { label: '核心人物候选', color: '#7C3AED', radius: 11 },
  P1: { label: 'P1 优先核查', color: '#C2410C', radius: 8 },
  P2: { label: 'P2 重点关注', color: '#2563EB', radius: 6 },
  P3: { label: 'P3 一般参考', color: '#64748B', radius: 5 },
  unassessed: { label: '未评估／依据不足', color: '#94A3B8', radius: 5 },
};
export const peopleStyle = assessment => PEOPLE_LEVELS[assessment?.core ? 'core' : assessment?.priority] || PEOPLE_LEVELS.unassessed;
export const IDENTITY_LABELS = { candidate: '人员候选', ambiguous: '同名待区分',
  identity_conflict: '身份标识冲突', recorded_identifier: '有材料记载身份标识', manually_grouped: '人工归组', manually_separated: '人工拆分' };
const LIMITS = {
  TOTAL_TEXT_BUDGET: '本轮总文本预算已用尽',
  TEXT_TRUNCATED: '仅处理文件的部分文本',
  DISCOVERY_CHUNK_BUDGET: '本轮人员识别预算已用尽',
  PERSON_DISCOVERY_INCOMPLETE: '部分人物识别或关系校验未完成',
  AMBIGUOUS_REGISTERED_PATH: '登记路径存在多个候选，未猜测来源',
  EXTRACTED_SOURCE_MISSING_OR_AMBIGUOUS: '提取副本缺失或来源不唯一',
  SOURCE_PATH_MISSING_OR_AMBIGUOUS: '登记文件来源不唯一或缺失',
  SOURCE_EXCEEDS_READ_BUDGET: '文件超过本轮读取上限',
  SOURCE_HASH_CHANGED: '来源与已记录哈希不一致',
  SOURCE_SIZE_CHANGED: '来源大小与记录不一致',
  SOURCE_CHANGED_DURING_READ: '读取期间文件发生变化',
  ORIGINAL_HASH_UNAVAILABLE: '没有可核对的原始记录哈希',
  PARSED_PROJECTION_COVERAGE_UNVERIFIED: '使用解析文本，原文件覆盖完整度尚未核验',
  DATABASE_FIRST_50_ROWS_ONLY: '数据库只读取结构和每表前50行样本',
  COMPANION_WAL_NOT_READ: '未读取配套WAL记录',
  MACHINE_TRANSCRIPT_UNVERIFIED: '使用机器转写，尚需核对音视频',
  MACHINE_VISUAL_TEXT_UNVERIFIED: '使用机器读取的图片文字，尚需人工核对',
  IMAGE_READING_BUDGET: '图片超过本轮读取数量或大小上限',
  INFERRED_TEXT_ENCODING: '采用推定的文本编码',
  PARSER_UNAVAILABLE: '当前格式解析器不可用',
  TRANSCRIPT_UNAVAILABLE: '缺少与来源匹配的可用转写',
  UNSUPPORTED_FORMAT: '当前格式尚不支持人员读取',
  NO_READABLE_TEXT: '没有可用的解析文字',
  UNREADABLE_BINARY: '内容是不可直接读取的二进制',
  SOURCE_READ_FAILED: '来源读取失败',
};
export const peopleLimitLabel = code => LIMITS[code] || '来源读取或识别未完整完成，需进一步核对';
const BASIS = { text: '冻结文字片段', parsed_text: '冻结解析文本，非原文件页码',
  machine_transcript: '机器转写，尚需核对音视频', machine_visual_text: '机器读取图片文字，尚需人工核对',
  initial_analysis: '初次分析摘要；尚未核对原文', graph_input: '建图输入记录，来源性质需核查',
  case_description: '案情语境，不作为材料佐证', unavailable: '来源不可读' };
export const peopleBasisLabel = kind => BASIS[kind] || '来源类型尚待核查';
