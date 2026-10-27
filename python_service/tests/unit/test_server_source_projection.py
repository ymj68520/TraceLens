import pytest
from httpserver.services.document_extractor import get_document_extractor_locator
from httpserver.services.extractors.base import DocumentContentUnavailableError


@pytest.mark.asyncio
@pytest.mark.parametrize('extension',['.php','.phtml','.jsp','.asp','.aspx','.py','.js','.sh'])
async def test_server_source_is_read_as_text_without_execution(tmp_path,extension):
    path=tmp_path/('source'+extension)
    text='<?php /* 配置中包含支付回调地址，仅表明代码存在 */ $route="/pay/notify"; ?>'
    path.write_text(text,encoding='utf-8')
    parser=get_document_extractor_locator().get_extractor(str(path))
    assert parser is not None
    parsed=await parser.extract_result(str(path))
    assert parsed.require_content()==text
    assert parsed.parser=='text'


@pytest.mark.asyncio
async def test_binary_disguised_as_php_remains_unreadable(tmp_path):
    path=tmp_path/'payload.php';path.write_bytes(b'<?php\x00\x01binary')
    parser=get_document_extractor_locator().get_extractor(str(path))
    with pytest.raises(DocumentContentUnavailableError):await parser.extract_result(str(path))


@pytest.mark.asyncio
@pytest.mark.parametrize('name,text', [
    ('nginx.conf', 'server {\n listen 80;\n server_name example.test;\n root /srv/site/public;\n location / { try_files $uri $uri/ /index.php?$query_string; }\n}\n'),
    ('ssh.conf', '# PermitRootLogin yes\nPermitRootLogin no\nMatch User backup\n PasswordAuthentication no\n'),
    ('my.cnf', '[mysqld]\ndatadir=/www/server/data\nport=3306\n!includedir /etc/my.cnf.d\n'),
    ('settings.ini', '[DEFAULT]\nPath=/srv/%user%/\n[site]\nKey=first\nKey=second\nToken=' + 'a' * 150 + '\n'),
])
async def test_config_projection_preserves_source_without_ini_reinterpretation(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding='utf-8')
    parser = get_document_extractor_locator().get_extractor(str(path))
    parsed = await parser.extract_result(str(path))
    assert parsed.require_content() == text
    assert parsed.parser == 'configuration_source_text'
    assert parsed.status == 'ok'


@pytest.mark.asyncio
async def test_corrupt_configuration_does_not_become_empty_success(tmp_path):
    path = tmp_path / 'site.conf'
    path.write_bytes(b'server_name \xff\x00;')
    parser = get_document_extractor_locator().get_extractor(str(path))
    with pytest.raises(DocumentContentUnavailableError):
        await parser.extract_result(str(path))


@pytest.mark.asyncio
async def test_config_budget_is_explicit_and_preserves_prefix(tmp_path):
    text = 'listen 80;\n' * 25000
    path = tmp_path / 'large.conf'
    path.write_text(text, encoding='utf-8')
    parser = get_document_extractor_locator().get_extractor(str(path))
    parsed = await parser.extract_result(str(path))
    assert parsed.status == 'partial'
    assert parsed.require_content() == text[:200000]
    assert parsed.coverage['truncated']
    assert parsed.diagnostics == ('TEXT_READ_BUDGET',)
