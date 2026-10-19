import pytest

from app.core.errors import AppError
from app.schemas.document import TextBlock
from app.services.exam_parser import (
    build_exam_text,
    extraction_windows,
    locate_quote,
    rule_extract,
    verify_number,
)


def test_cross_page_options_duplicate_numbers_and_metadata():
    blocks = [
        TextBlock(
            text="一、选择题\n1. A* 的评价函数？（2分）\nA. g+h", page=1, location_type="pdf_page"
        ),
        TextBlock(
            text="B. g-h\n二、简答题\n1. 解释启发式。【知识点：A*、启发式函数】",
            page=2,
            location_type="pdf_page",
        ),
    ]
    parsed = build_exam_text(blocks)
    questions = rule_extract(parsed.text)
    assert len(questions) == 2
    assert [q.number for q in questions] == ["1", "1"]
    assert questions[0].options == ["A. g+h", "B. g-h"]
    assert questions[0].score == 2
    start, end = locate_quote(parsed.text, questions[0].source_text)
    assert [loc["page"] for loc in parsed.locations(start, end)] == [1, 2]
    assert questions[1].knowledge_points == ["A*", "启发式函数"]
    assert questions[1].type == "short_answer"


def test_quote_validation_and_window_bounds():
    assert locate_quote("1. hello\n world", "1. hello world") == (0, 15)
    with pytest.raises(AppError):
        locate_quote("1. hello world", "1. fabricated")
    text = "\n".join(f"{i}. " + "题干" * 150 for i in range(1, 50))
    windows = extraction_windows(text, 4000)
    assert all(len(window) <= 4000 for _, window in windows)
    assert all(text[offset : offset + len(window)] == window for offset, window in windows)
    assert windows[-1][0] + len(windows[-1][1]) == len(text)


def test_all_question_types_and_answer_section():
    text = "一、判断题\n1、真吗？\n二、填空题\n2、____\n三、计算题\n3、计算。\n四、综合题\n4、论述。\n参考答案\n1、真"
    assert [q.type for q in rule_extract(text)] == [
        "true_false",
        "fill_blank",
        "calculation",
        "essay",
    ]


def test_question_number_is_not_a_score_or_year():
    verify_number("12", "第12题：解释 A*")
    verify_number("12", "（12）解释 A*")
    with pytest.raises(AppError, match="题号"):
        verify_number("2", "1. 解释 A*（2分）")


def test_chapter_question_numbers_and_code_are_preserved():
    text = "第一章 操作系统\n习题\n1.1 定义操作系统。\n1.2 说明 I/O。\n第二章 进程管理\n习题\n2.10 [必做]修改代码：\nwait(full);\nsignal(mutex);\n2.11 解释线程。"
    questions = rule_extract(text)
    assert [q.number for q in questions] == ["1.1", "1.2", "2.10", "2.11"]
    assert questions[1].source_text == "1.2 说明 I/O。"
    assert "wait(full);\nsignal(mutex);" in questions[2].source_text
    for question in questions:
        verify_number(question.number, question.source_text)
    with pytest.raises(AppError):
        verify_number("2", "2.10 [必做]修改代码：")
    windows = extraction_windows(text, 65)
    assert any(window.startswith("2.10") for _, window in windows)
    assert all(len(window) <= 65 for _, window in windows)


def test_quote_layout_normalization_keeps_math_and_source_offsets():
    text = "前文\n２．１０ [必做]Ａ（x）＝x²\u200b + 1；\n后文"
    start, end = locate_quote(text, "2.10 [必做]A(x)=x² + 1;")
    assert text[start:end] == "２．１０ [必做]Ａ（x）＝x²\u200b + 1；"
    for fabricated in ["2.10 [必做]A(x)=x2 + 1;", "2.10 [必做]A(x)=x² - 1;"]:
        with pytest.raises(AppError):
            locate_quote(text, fabricated)


def test_pdf_page_counters_removed_but_locations_preserved():
    parsed = build_exam_text([
        TextBlock(text="第 3 页 共 10 页\n2.1 跨页题目开始", page=3, location_type="pdf_page"),
        TextBlock(text="第 4 页 共 10 页\n接着上一页的代码。\n2.2 下一题", page=4, location_type="pdf_page"),
    ])
    question = rule_extract(parsed.text)[0]
    assert question.number == "2.1" and "第 4 页" not in question.source_text
    start, end = locate_quote(parsed.text, question.source_text)
    assert [location["page"] for location in parsed.locations(start, end)] == [3, 4]
