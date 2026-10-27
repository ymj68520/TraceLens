"""Bounded Linux/glibc utmp records; record offsets and UTC times stay explicit."""
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import struct
from .base import BaseExtractor,ExtractionResult,DocumentContentUnavailableError,register_extractor


@register_extractor
class LinuxUtmpExtractor(BaseExtractor):
    size=384
    labels={0:'空槽位',1:'运行级别',2:'系统启动',3:'新时间',4:'旧时间',5:'初始化进程',6:'登录进程',7:'用户会话',8:'进程结束',9:'记账'}
    def __init__(self,max_records=5000):self.max_records=max(1,min(int(max_records),5000))
    async def extract_to_markdown(self,file_path):return (await self.extract_result(file_path)).require_content()
    def parse_record(self,data,index):
        if len(data)!=self.size:return None
        kind=struct.unpack_from('<h',data,0)[0]
        if kind not in self.labels or not any(data):return None
        warnings=[]
        def field(start,size):
            raw=data[start:start+size].split(b'\0',1)[0]
            try:
                value=raw.decode('utf-8')
                if any(ord(c)<32 for c in value):raise UnicodeError()
                return value
            except UnicodeError:
                warnings.append('UTMP_TEXT_BYTES_ESCAPED');return '原始字节0x'+raw.hex()
        sec,usec=struct.unpack_from('<ii',data,340);stamp=None
        if sec>0 and 0<=usec<1000000:
            stamp=datetime.fromtimestamp(sec,timezone.utc).replace(microsecond=usec).isoformat(timespec='microseconds' if usec else 'seconds').replace('+00:00','Z')
        else:warnings.append('UTMP_TIME_UNKNOWN')
        return {'record_index':index,'byte_offset':index*self.size,'record_type':kind,'record_label':self.labels[kind],
                'pid':struct.unpack_from('<i',data,4)[0], 'terminal':field(8,32),'user':field(44,32),'hostname':field(76,256),
                'raw_seconds':sec,'raw_microseconds':usec,'timestamp_utc':stamp,'warnings':warnings}
    async def extract_result(self,file_path):
        path=Path(file_path)
        try:
            size=path.stat().st_size;total=size//self.size
            if size==0:return ExtractionResult('empty','linux-utmp','2',coverage={'record_count':0,'source_bytes':0},diagnostics_separated=True)
            if total==0:return ExtractionResult('error','linux-utmp','2',diagnostics=('UTMP_TRUNCATED_RECORD',),diagnostics_separated=True)
            indices=list(range(total)) if total<=self.max_records else list(range(self.max_records//2))+list(range(total-(self.max_records-self.max_records//2),total))
            records=[];invalid=0;empty=0
            with path.open('rb') as stream:
                for index in indices:
                    stream.seek(index*self.size);data=stream.read(self.size)
                    if not any(data):empty+=1;continue
                    record=self.parse_record(data,index)
                    if record:records.append(record)
                    else:invalid+=1
        except OSError as error:raise DocumentContentUnavailableError('Linux登录记录无法读取',code='UTMP_READ_FAILED') from error
        notes=set(n for r in records for n in r['warnings'])
        if len(indices)<total:notes.add('UTMP_RECORDS_SAMPLED')
        if size%self.size:notes.add('UTMP_TRAILING_BYTES')
        if invalid:notes.add('UTMP_INVALID_RECORDS')
        if not records:return ExtractionResult('error' if invalid or notes else 'empty','linux-utmp','2',diagnostics=tuple(sorted(notes or {'UTMP_NO_VALID_RECORDS'})),coverage={'record_count':0,'invalid_records':invalid},diagnostics_separated=True)
        chosen=records if len(records)<=40 else records[:10]+records[-30:]
        lines=['# Linux登录记录（只读解析）','布局：Linux glibc utmp，384字节、小端；时间按记录中的Unix秒解释为UTC。',
               f'原记录槽位：{total}；实际检查：{len(indices)}；所读有效记录：{len(records)}。',
               '以下按文件位置展示记录；用户会话记录不等于授权结论，未知时间不作推断。',
               '| 字节偏移 | 记录时间UTC | 类型 | 用户 | 终端 | 远端 |','| --- | --- | --- | --- | --- | --- |']
        displayed=[]
        for record in chosen:
            values=[record['byte_offset'],record['timestamp_utc'] or '未知',record['record_label'],record['user'] or '未知',record['terminal'] or '未知',record['hostname'] or '未知']
            line='| '+' | '.join(str(v).replace('|','\\|').replace('\n',' ') for v in values)+' |'
            if sum(len(v)+1 for v in lines)+len(line)>3700:continue
            lines.append(line);displayed.append(record['record_index'])
        if len(displayed)<len(records):notes.add('UTMP_OUTPUT_SAMPLED');lines.append('部分记录未在本轮文本展开，不能据此认定没有其他登录或活动。')
        coverage={'source_bytes':size,'total_record_slots':total,'scanned_records':len(indices),'record_count':len(records),
                  'displayed_records':len(displayed),'displayed_record_indices':displayed,'invalid_records':invalid,'empty_slots':empty,'type_counts':dict(Counter(r['record_label'] for r in records))}
        return ExtractionResult('partial' if notes else 'ok','linux-utmp','2',text='\n'.join(lines),records=tuple(records),
                                diagnostics=tuple(sorted(notes)),coverage=coverage,diagnostics_separated=True)
