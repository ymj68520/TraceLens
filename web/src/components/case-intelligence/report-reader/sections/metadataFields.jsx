/**
 * Field definitions for the editable case-info / evidence-info metadata.
 *
 * Mirrors the reference report 案件信息 (~20 fields) and 证据信息 (~21 fields).
 * `key` must match the backend `report_metadata` column; `label` is the display
 * string shown in both the read-only section and the editor form.
 */

export const CASE_INFO_FIELDS = [
  { key: 'case_name', label: '案件名称' },
  { key: 'case_number', label: '案件编号' },
  { key: 'case_type', label: '案件类型' },
  { key: 'law_case_number', label: '执法办案系统案件编号' },
  { key: 'law_case_category', label: '执法办案系统案件类别' },
  { key: 'law_case_name', label: '执法办案系统案件名称' },
  { key: 'collector_name', label: '采集人姓名' },
  { key: 'collector_id', label: '采集人编号' },
  { key: 'collector_id_card', label: '采集人身份证号' },
  { key: 'collector_unit', label: '采集单位' },
  { key: 'submitter1_name', label: '送检人姓名1' },
  { key: 'submitter1_id', label: '送检人编号1' },
  { key: 'submitter2_name', label: '送检人姓名2' },
  { key: 'submitter2_id', label: '送检人编号2' },
  { key: 'submitter_unit', label: '送检单位' },
  { key: 'inspection_number', label: '勘验编号' },
  { key: 'alarm_id', label: '接警单号' },
  { key: 'alarm_code', label: '警情编码' },
  { key: 'remarks', label: '备注' },
];

export const EVIDENCE_INFO_FIELDS = [
  { key: 'evidence_name', label: '证据名称' },
  { key: 'evidence_number', label: '证据编号' },
  { key: 'phone1', label: '手机号码1' },
  { key: 'phone2', label: '手机号码2' },
  { key: 'holder', label: '持有人' },
  { key: 'holder_id', label: '持有人编号' },
  { key: 'holder_type', label: '持有人类型' },
  { key: 'id_type', label: '证件类型' },
  { key: 'id_number', label: '证件编号' },
  { key: 'extract_start', label: '开始提取时间' },
  { key: 'extract_end', label: '提取完成时间' },
  { key: 'evidence_remarks', label: '备注' },
  { key: 'holder_gender', label: '持有人性别' },
  { key: 'holder_ethnicity', label: '持有人民族' },
  { key: 'birth_date', label: '出生日期' },
  { key: 'current_address', label: '现住址详址' },
  { key: 'registered_address', label: '户籍地详址' },
  { key: 'id_issue_authority', label: '证件签发机关' },
  { key: 'id_valid_from', label: '证件生效日期' },
  { key: 'id_valid_to', label: '证件失效日期' },
];

export const ALL_METADATA_FIELDS = [...CASE_INFO_FIELDS, ...EVIDENCE_INFO_FIELDS];
