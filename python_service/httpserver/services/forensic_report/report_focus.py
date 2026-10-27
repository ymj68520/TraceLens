"""Source-role diversity for a report, without treating a filename as behaviour."""
import re
from urllib.parse import unquote

def role(material):
    key=unquote(material.evidence_key).lower()
    provenance=material.source_provenance or {}
    table=provenance.get('source_table') or (key.split(':')[-2] if key.startswith('windows_artifact:') else '')
    if table in ('scheduled_tasks','windows_services'):
        return 5,'system_configuration',table
    if table:
        return 1,'activity',table
    path=(provenance.get('locator') or {}).get('logical_path') or key
    path=path.lower()
    for marker in ('/public/static/plugs/','/public/static/plugins/','/usr/src/kernels/','/var/lib/yum/yumdb/',
                   '/_locales/','/locales/','/node_modules/','/site-packages/','/vendor/','/thinkphp/','/mysql-test/','/winsxs/','/usr/share/','/usr/lib/'):
        if marker in path:return 8,'software_resource',path.split(marker)[0]+marker
    if ('/usr/local/' in path and '/man/man' in path) or ('/var/log/anaconda/' in path and path.endswith('.hdr')):
        return 8,'software_resource',path.rsplit('/',1)[0]
    if any(v in path for v in ('/system32/tasks/','/systemapps/','/windowsapps/')):
        return 5,'system_configuration',path.rsplit('/',2)[0]
    if any(v in path for v in ('/var/log/','/www/wwwlogs/','/.bash_history','/.zsh_history','/prefetch/','/winevt/logs/')):
        return 0,'activity',path.rsplit('/',1)[0]
    name=path.rsplit('/',1)[-1]
    if any(v in path for v in ('/panel/vhost/','/etc/nginx/','/etc/httpd/','/etc/apache2/')):
        return 0,'service_configuration',path.rsplit('/',1)[0]
    if name in ('database.php','.env','my.cnf','sshd_config','settings.xml','default.xml','authorized_keys','known_hosts'):
        return 0,'application_configuration',path.rsplit('/',1)[0]
    if any(v in path for v in ('/www/wwwroot/','/var/www/','/srv/')):
        site=re.split(r'/(?:www/wwwroot|var/www|srv)/',path,maxsplit=1)[-1].split('/')[0]
        if '/file_history/' in path:return 3,'user_material','historical:'+site
        return 1,'application_logic',site+':'+path.rsplit('/',2)[0]
    if name in ('os-release','centos-release','redhat-release','hostname'):
        return 1,'environment','os_identity'
    if any(v in path for v in ('/desktop/','/documents/','/downloads/','/home/','/root/')):
        return 2,'user_material',path.rsplit('/',1)[0]
    if '/etc/' in path:return 3,'environment',path.rsplit('/',1)[0]
    return 4,'other',path.rsplit('/',1)[0]


def choose(findings,limit,spans,materials,legacy_rank):
    metadata={}
    for finding in findings:
        candidates=[role(materials[spans[r].material_id]) for r in (*finding.supporting_spans,*finding.counter_spans)]
        metadata[finding.finding_id]=min(candidates) if candidates else (6,'case_context','case_context')
    remaining=list(findings);selected=[];groups={};topics={}
    while remaining and len(selected)<limit:
        def key(f):
            weight,topic,group=metadata[f.finding_id]
            importance=0 if f.priority_hint=='P1' else 1 if f.priority_hint=='P2' else 2
            return (weight+min(2,groups.get(group,0)//3),importance,topics.get(topic,0),groups.get(group,0),legacy_rank(f))
        chosen=min(remaining,key=key);remaining.remove(chosen);selected.append(chosen)
        _,topic,group=metadata[chosen.finding_id];groups[group]=groups.get(group,0)+1;topics[topic]=topics.get(topic,0)+1
    return selected


def thread(findings,spans,materials):
    labels={'activity':'访问、执行与运维记录','service_configuration':'服务暴露与站点配置',
        'application_configuration':'应用连接与账户配置','application_logic':'应用功能及业务数据结构',
        'environment':'设备与系统背景','user_material':'用户保存的材料','other':'其他可核查材料',
        'system_configuration':'系统配置的证据边界','software_resource':'软件资源的证据边界','case_context':'待核调查问题'}
    topics=[]
    for finding in findings:
        for ref in (*finding.supporting_spans,*finding.counter_spans):
            label=labels[role(materials[spans[ref].material_id])[1]]
            if label not in topics:topics.append(label)
    return '围绕'+ '、'.join(topics[:4])+'组织材料之间可验证的联系；把配置声明、记录中的实际活动和待核假设分开。关键观察：'+'；'.join(f.statement for f in findings[:3])
