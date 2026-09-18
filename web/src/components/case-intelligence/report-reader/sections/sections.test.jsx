/**
 * Tests for the structured report sections.
 * The key contract: every reference-report field renders, and empty values
 * show the "—" placeholder so the report schema is always fully visible.
 * Platform sections are now rendered by the generic table via artifactColumns.
 */
import { screen } from '@testing-library/react';
import { renderWithRouter } from '../../../../test/renderWithRouter';
import CaseInfoSection from './CaseInfoSection';
import EvidenceInfoSection from './EvidenceInfoSection';
import DeviceInfoSection from './DeviceInfoSection';
import GenericArtifactTable from './GenericArtifactTable';

describe('CaseInfoSection', () => {
  test('renders all case-info fields, showing "—" for empty values', () => {
    renderWithRouter(
      <CaseInfoSection metadata={{ case_name: '电信诈骗案', collector_name: '王警官' }} />,
    );
    expect(screen.getByText('电信诈骗案')).toBeInTheDocument();
    expect(screen.getByText('王警官')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    expect(screen.getByText('案件编号')).toBeInTheDocument();
    expect(screen.getByText('采集单位')).toBeInTheDocument();
  });

  test('renders every label even with fully empty metadata', () => {
    renderWithRouter(<CaseInfoSection metadata={{}} />);
    expect(screen.getByText('案件名称')).toBeInTheDocument();
    expect(screen.getByText('警情编码')).toBeInTheDocument();
    expect(screen.getByText('备注')).toBeInTheDocument();
  });

  test('badges only the fields that hold an auto-derived value', () => {
    renderWithRouter(
      <CaseInfoSection
        metadata={{ case_name: '服务器镜像案', collector_name: '王警官' }}
        autoFields={['case_name']}
      />,
    );
    // exactly one badge, on the auto-derived field
    expect(screen.getAllByText('自动')).toHaveLength(1);
    expect(screen.getByText('自动').closest('dt')).toHaveTextContent('案件名称');
  });

  test('renders no badge when autoFields is absent', () => {
    renderWithRouter(<CaseInfoSection metadata={{ case_name: '电信诈骗案' }} />);
    expect(screen.queryByText('自动')).not.toBeInTheDocument();
  });
});

describe('EvidenceInfoSection', () => {
  test('renders all evidence-info fields', () => {
    renderWithRouter(
      <EvidenceInfoSection metadata={{ evidence_name: '张洋办公手机', holder: '张洋' }} />,
    );
    expect(screen.getByText('张洋办公手机')).toBeInTheDocument();
    expect(screen.getByText('张洋')).toBeInTheDocument();
    expect(screen.getByText('持有人类型')).toBeInTheDocument();
    expect(screen.getByText('证件失效日期')).toBeInTheDocument();
  });

  test('badges auto-derived evidence fields', () => {
    renderWithRouter(
      <EvidenceInfoSection
        metadata={{ evidence_name: '服务器镜像.E01', evidence_number: '08a92dd8' }}
        autoFields={['evidence_name', 'evidence_number']}
      />,
    );
    expect(screen.getAllByText('自动')).toHaveLength(2);
  });
});

describe('DeviceInfoSection', () => {
  test('renders every item label with placeholder parity', () => {
    renderWithRouter(
      <DeviceInfoSection pageData={{ records: [{ '设备型号': 'P30', 'IMEI': '', 'Wi-Fi地址': '' }] }} />,
    );
    expect(screen.getByText('设备型号')).toBeInTheDocument();
    expect(screen.getByText('P30')).toBeInTheDocument();
    expect(screen.getByText('IMEI')).toBeInTheDocument();
    expect(screen.getByText('Wi-Fi地址')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });

  test('shows placeholder text when no device info at all', () => {
    renderWithRouter(<DeviceInfoSection pageData={{ records: [] }} />);
    expect(screen.getByText(/未检测到设备基本信息/)).toBeInTheDocument();
  });

  test('labels the platform from the section category, using the backend title', () => {
    const cases = [
      ['device_info', '设备基本信息（Android）', 'Android'],
      ['win_device_info', '设备基本信息（Windows）', 'Windows'],
      ['linux_device_info', '设备基本信息（Linux）', 'Linux'],
    ];
    for (const [category, title, platform] of cases) {
      const { unmount } = renderWithRouter(
        <DeviceInfoSection
          pageData={{ category, records: [{ 主机名: 'srv-01' }] }}
          title={title}
        />,
      );
      expect(screen.getByText(title)).toBeInTheDocument();
      expect(screen.getByText(platform)).toBeInTheDocument();
      unmount();
    }
  });

  test('shows no platform chip for the undetermined-platform fallback', () => {
    renderWithRouter(
      <DeviceInfoSection
        pageData={{ category: 'device_info_generic', records: [] }}
        title="设备基本信息"
      />,
    );
    expect(screen.getByText('设备基本信息')).toBeInTheDocument();
    expect(screen.queryByText('Android')).not.toBeInTheDocument();
  });
});

describe('GenericArtifactTable — Android contacts', () => {
  test('renders columns from the registry and formats rows', () => {
    renderWithRouter(
      <GenericArtifactTable sectionId="contacts" title="通讯录" pageData={{
        page: 1, page_size: 50, total: 1,
        records: [{ display_name: '张三', phone_number: '13800000001', email: '' }],
      }} />,
    );
    expect(screen.getByText('通讯录')).toBeInTheDocument();
    expect(screen.getByText('张三')).toBeInTheDocument();
    expect(screen.getByText('13800000001')).toBeInTheDocument();
    // empty email renders placeholder
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    // registry column labels
    expect(screen.getByText('姓名')).toBeInTheDocument();
    expect(screen.getByText('邮箱')).toBeInTheDocument();
  });

  test('shows empty placeholder with zero records', () => {
    renderWithRouter(<GenericArtifactTable sectionId="contacts" title="通讯录" pageData={{ records: [], total: 0 }} />);
    expect(screen.getByText('该分类暂无记录。')).toBeInTheDocument();
  });
});

describe('GenericArtifactTable — Windows users', () => {
  test('renders Windows-specific columns', () => {
    renderWithRouter(
      <GenericArtifactTable sectionId="win_users" title="用户账户" pageData={{
        page: 1, page_size: 50, total: 1,
        records: [{ username: 'Administrator', is_admin: 1, last_login: 1607300000 }],
      }} />,
    );
    expect(screen.getByText('Administrator')).toBeInTheDocument();
    // is_admin formatted to 是
    expect(screen.getByText('是')).toBeInTheDocument();
    expect(screen.getByText('用户名')).toBeInTheDocument();
    expect(screen.getByText('管理员')).toBeInTheDocument();
  });
});

describe('GenericArtifactTable — Linux shell history', () => {
  test('renders Linux-specific columns', () => {
    renderWithRouter(
      <GenericArtifactTable sectionId="linux_shell" title="Shell历史" pageData={{
        page: 1, page_size: 50, total: 1,
        records: [{ username: 'root', command: 'nmap 10.0.0.1', timestamp: 1607300100 }],
      }} />,
    );
    expect(screen.getByText('root')).toBeInTheDocument();
    expect(screen.getByText('nmap 10.0.0.1')).toBeInTheDocument();
    expect(screen.getByText('命令')).toBeInTheDocument();
    // shell_type column absent in this record → not rendered
    expect(screen.queryByText('Shell类型')).not.toBeInTheDocument();
  });
});

describe('GenericArtifactTable — unknown section fallback', () => {
  test('derives columns from record keys when no registry entry', () => {
    renderWithRouter(
      <GenericArtifactTable sectionId="new_unknown_section" title="新章节" pageData={{
        page: 1, page_size: 50, total: 1,
        records: [{ custom_field: '值A', another: '值B' }],
      }} />,
    );
    // unknown columns use raw key names as labels
    expect(screen.getByText('custom_field')).toBeInTheDocument();
    expect(screen.getByText('值A')).toBeInTheDocument();
  });
});
