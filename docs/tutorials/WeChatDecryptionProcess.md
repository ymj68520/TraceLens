# 微信数据库解密过程（EnMicroMsg.db，微信 8.0.76）

本文档记录从小米整机备份（`微信(com.tencent.mm).bak`，MIUI BACKUP v2）中
提取并解密安卓微信主数据库 `EnMicroMsg.db` 的完整过程。方法为**页面级检测 +
纯 Python 逐页解密**，不依赖 SQLCipher 工具——可绕开解密后
"file is not a database" 的 HMAC 误报陷阱。

复现工具位于 `~/projects/testimgs/MIUIBackup/`：

| 脚本 | 用途 |
|---|---|
| `wechat_extract.py` | 流式解包备份（65B 文本头 + tar），提取密钥材料与账号文件 |
| `wechat_decrypt.py` | 单库解密（derive / page / auto 三模式） |
| `batch_decrypt.py` | 批量页面级检测 + 解密整个账号目录 |

服务内实现同源：`python_service/httpserver/services/wechat_decrypt.py`。

## 1. 从备份提取密钥材料

备份结构为 65 字节文本头（`MIUI BACKUP\n2\ncom.tencent.mm …`）+ 标准 tar。
流式扫描提取 4887 个条目，其中与解密相关的：

| 材料 | 值 | 出处 |
|---|---|---|
| UIN | `1583567084` | `shared_prefs/system_config_prefs.xml` 的 `default_uin`；`files/recovery_v3/last_uin` |
| IMEI | `1234567890ABCDEF`（真机取不到，回退固定值） | `files/KeyInfo.bin`（RC4，密钥 `_wEcHAT_`）|
| wxid | `wxid_xl6fbcymzzlp22` | `shared_prefs/com.tencent.mm_preferences.xml` 的 `login_weixin_username` |
| 账号目录 | `aecac96c78f6c9914678027a86cdccf9` | `MicroMsg/<hash>/`，= `MD5("mm" + UIN)`，交叉验证通过 |

> **服务内自动化**：取证导入（`/api/wechat/forensics/imports`）在未给口令、
> 也未给 UIN 时，会自动执行上表的收集——`wechat_import_service._harvest_key_material`
> 从 `EnMicroMsg.db` 周边的提取树就地读取 `shared_prefs/*.xml`（UIN / wxid）与
> `CompatibleInfo.cfg`（Java 序列化映射，键 258/256，即设备 ID），写进
> meta.json 的 `key_material` 留痕后进入候选推导。本节的手工提取流程仍是
> MIUI `.bak` 尚未解包、或库文件已脱离提取树时的兜底。

## 2. 口令推导公式

- 主库口令 = `MD5(IMEI + UIN)[:7]` = `93f2dd5`
- FTS 索引库口令 = `MD5(UIN + IMEI + wxid)[:7]` = `d95ef98`

推导产生候选口令列表后，用页面级检测确认（见下节），不需要逐个盲试。

## 3. 页面级检测（核心，避开 HMAC 陷阱）

直接让 SQLCipher 工具打开常常报 "file is not a database"，原因是微信库
**无 HMAC 校验**，而工具默认按有 HMAC 的参数验证。改为逐页验证：

对每个候选口令与参数组合：

1. 用 `PBKDF2-HMAC-SHA1`（迭代次数、盐来自第 1 页前 16 字节）派生 32B 密钥；
2. 用 **AES-256-CBC** 解密第 1 页（IV = 该页末尾 16 字节，保留区不校验）；
3. 拼回页头：明文第 1 页 = `SQLite format 3\0`(16B) + 密文区解密结果 +
   保留区补零；非首页 = 密文区解密结果 + 保留区补零；
4. 校验 SQLite 页头特征：页大小（大端 2 字节）、读写版本 ∈ {1,2}、
   `bytes[5..8] == 64,32,32`。全部命中即确认口令与方案。

## 4. 实测命中的加密参数（微信 8.0.76）

| 方案 | 页大小 | KDF | 密码算法 | 保留区 | 适用库 |
|---|---|---|---|---|---|
| A（主库） | 1024 | PBKDF2-HMAC-SHA1 ×4000 → 32B | AES-256-CBC 逐页，无 HMAC，IV=页尾 16B | 16B | EnMicroMsg.db、AppBrandComm、Edge、WxCgiReport、WxExpt、WxFileIndex、enFavorite、newuba |
| B（FTS） | 4096 | PBKDF2-HMAC-SHA1 ×64000 | 同上 | 48B（IV 前 16B + 32B 校验） | FTS5IndexMicroMsg_encrypt.db |

## 5. WAL 解密与合并

`EnMicroMsg.db-wal` 也是加密的，必须一并处理，否则最新写入的消息丢失：

1. 逐帧（24B 明文帧头 + 加密页）解密；
2. **跳过盐值不等于 WAL 头盐的帧**（陈旧代次的残留帧）；
3. 按 SQLite 官方校验和算法（魔数 `0x377f0682` ⇒ 小端）重算帧校验链，
   使标准 SQLite 能够接受回放；
4. 合并进主库。本次 183 帧中 8 帧盐值匹配并保留。

## 6. 结果

- `decrypted_output/`：34 个库（8 个加密库解密 + 26 个原本明文）；
- `EnMicroMsg.db`：`PRAGMA integrity_check = ok`，154 条消息、47 联系人、
  1 群聊全部可读（中文昵称 / 备注 / 群名已还原）；
- 密钥材料与提取清单留档于 `wechat_extracted/`（`bak_entries.txt`）。

## 7. 陷阱记录

1. **HMAC 误报**：不要相信工具直接打开报的 "file is not a database"，
   先做页面级检测。
2. **第 1 页拼接**：密文区从文件偏移 16 开始（前 16B 是明文盐），
   解密结果对应页内偏移 16..页大小，拼页头时不要错位。
3. **IMEI 回退**：真机取不到 IMEI 时，微信历史版本大量使用固定值
   `1234567890ABCDEF`，优先尝试。
4. **WAL 盐过滤**：不匹配的帧必须丢弃，否则校验链断裂导致回放失败。
