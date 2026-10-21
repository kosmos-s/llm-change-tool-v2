import ast
import re
from pathlib import Path

import llm_change_tool
from llm_change_tool.ui.feedback import explain_error

FALLBACK = "작업을 완료하지 못했습니다. 상세 기록"


def raised_messages():
    root = Path(llm_change_tool.__file__).parent
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call)):
                continue
            if not node.exc.args:
                continue
            arg = node.exc.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                text = arg.value
            elif isinstance(arg, ast.JoinedStr):
                text = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in arg.values)
            else:
                continue
            yield f"{path.relative_to(root)}:{node.lineno}", text


def test_every_english_error_has_a_korean_message():
    # AGENTS rule: user-visible errors are Korean and say what to do next.
    missing = []
    for place, text in raised_messages():
        # Wrappers that start with another message are explained by that message.
        if re.search("[가-힣]", text) or text.startswith("{}"):
            continue
        sample = text.replace("http_{}", "http_400").replace("{}", "X")
        if explain_error(sample).startswith(FALLBACK):
            missing.append(f"{place} {text!r}")
    assert missing == []


def test_restoring_a_non_database_file_explains_next_step(tmp_path):
    import pytest

    from llm_change_tool.core.projects import restore_project

    bad = tmp_path / "not-a-backup.sqlite3"
    bad.write_bytes(b"not sqlite")
    with pytest.raises(Exception) as caught:
        restore_project(bad, tmp_path / "restored")
    message = explain_error(str(caught.value))
    assert not message.startswith(FALLBACK) and "백업 파일을 다시 선택" in message
    assert not (tmp_path / "restored").exists()


def test_http_client_errors_have_specific_guidance():
    assert "http_404" in explain_error("http_404")
    assert explain_error("http_401") != explain_error("http_404")
    assert explain_error("http_503").startswith("AI 서버 오류")
