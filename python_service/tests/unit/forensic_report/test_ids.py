from httpserver.services.forensic_report.ids import safe_segment, stable_record_id


def test_stable_record_id_ignores_pagination_order():
    first = stable_record_id(
        evidence_id="task-1",
        platform="android",
        category="sms",
        source_table="sms_messages",
        source_record_id="42",
    )
    second = stable_record_id("task-1", "android", "sms", "sms_messages", "42")
    assert first == second
    assert first.startswith("rec_")
    assert len(first) == 68


def test_safe_segment_rejects_path_traversal_and_is_deterministic():
    assert safe_segment("微信/聊天 ../ records") == safe_segment("微信/聊天 ../ records")
    assert "/" not in safe_segment("微信/聊天 ../ records")
    assert ".." not in safe_segment("微信/聊天 ../ records")
