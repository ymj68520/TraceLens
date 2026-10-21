"""Chinese display/LLM contracts preserve historical prompts and evidence."""
from httpserver.services.investigation.prompts import (
    get_prompt, get_event_refresh_prompt, CURRENT_PROMPT_VERSION,
    ANDROID_PROMPT_VERSION, EVENT_REFRESH_PROMPT_VERSION,
    SECONDARY_ANALYSIS_SYSTEM_V3, EVENT_REFRESH_SYSTEM_V1,
)
from httpserver.services.report_rendering import (
    REPORT_RENDER_PROMPTS, REPORT_RENDER_PROMPT_VERSION, REPORT_RENDER_SYSTEM_PROMPT_V1,
)
from httpserver.services.forensic_report.generation_prompts import (
    STAGE_DISCOVERY_SYSTEM_V1, STAGE_DISCOVERY_SYSTEM_V2,
    STAGE_COMPARE_SYSTEM_V1, STAGE_COMPARE_SYSTEM_V2,
)


def test_new_prompts_require_chinese_but_replay_keeps_historical_text():
    assert get_prompt('investigation-evidence-analysis:v3')[0] == SECONDARY_ANALYSIS_SYSTEM_V3
    assert get_event_refresh_prompt('investigation-event-refresh:v1')[0] == EVENT_REFRESH_SYSTEM_V1
    for version in (CURRENT_PROMPT_VERSION, ANDROID_PROMPT_VERSION):
        prompt, _ = get_prompt(version)
        assert '简体中文' in prompt and '证据引文逐字保留原文' in prompt
    assert '简体中文' in get_event_refresh_prompt(EVENT_REFRESH_PROMPT_VERSION)[0]
    assert REPORT_RENDER_PROMPTS['report-render-v1'] == REPORT_RENDER_SYSTEM_PROMPT_V1
    assert '简体中文' in REPORT_RENDER_PROMPTS[REPORT_RENDER_PROMPT_VERSION]
    assert STAGE_DISCOVERY_SYSTEM_V2.startswith(STAGE_DISCOVERY_SYSTEM_V1)
    assert STAGE_COMPARE_SYSTEM_V2.startswith(STAGE_COMPARE_SYSTEM_V1)
    assert '所有标题' in STAGE_DISCOVERY_SYSTEM_V2
    assert '证据引文保持原样' in STAGE_COMPARE_SYSTEM_V2
