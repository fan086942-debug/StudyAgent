import re


def solution_requested(question):
    """Separate solving from pure lookup and workspace management."""
    if re.search(
        r"查找|搜索|检索|定位|哪里|哪页|页码|哪些题|相关题|怎么考|考过|"
        r"学习进度|错题本|复习计划|学习计划|列出|统计",
        question,
    ) and not re.search(r"解答|求解|给出答案|参考答案|解题步骤", question):
        return False
    return bool(re.search(
        r"解答|回答|答题|做题|帮我做|解释|解析|分析|求解|计算|证明|推导|为什么|为何|如何|怎么|"
        r"是什么|什么是|讲解|说明|答案|第\s*[\d一二三四五六七八九十百.]+\s*(?:个|道)?题|[?？]", question,
    ))

NUMBER = r"(?:\d+|[零一二两三四五六七八九十百]+)"


def _ordinal(value):
    if value.isdigit():
        return int(value)
    digits = dict(zip("零一二两三四五六七八九", (0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9)))
    total, digit = 0, 0
    for char in value:
        if char in digits:
            digit = digits[char]
        else:
            total += (digit or 1) * (10 if char == "十" else 100)
            digit = 0
    return total + digit


def chapter_question_number(question):
    """A lookup candidate, never a substitute for finding the actual exercise."""
    match = re.search(
        rf"第\s*({NUMBER})\s*章\s*(?:的\s*)?(?:习题\s*)?第\s*({NUMBER})\s*(?:个|道)?\s*题(?:目)?",
        question,
    )
    if match:
        return f"{_ordinal(match[1])}.{_ordinal(match[2])}"
    return None


def referenced_question_number(question):
    chapter = chapter_question_number(question)
    if chapter:
        return chapter
    match = re.search(
        rf"第\s*({NUMBER}(?:\s*[.．]\s*\d+)*)\s*(?:个|道)?\s*题(?:目)?", question,
    )
    if match:
        return ".".join(str(_ordinal(part.strip())) for part in re.split(r"[.．]", match[1]))
    return None


COUNT = rf"({NUMBER})\s*(?:道(?:题目?)?|题目?)"
NEGATED_GENERATION = (
    r"(?:不要|不用|不需要|无需|不必|别).{0,12}(?:出|生成|制作|准备).{0,20}(?:题|卷|复习)"
)
EXAM_ACTION = rf"(?:生成|制作|准备).{{0,160}}(?:题|卷)|出\s*{NUMBER}\s*(?:道|题|套|份|张)|(?<![给列提指])出\s*(?:题|卷)|再(?:来|给我)?\s*{NUMBER}\s*(?:道|题)|模拟卷|模拟试卷"


def question_count(question):
    match = re.search(COUNT, question)
    if not match:
        return None
    value = match[1]
    if value.isdigit():
        return int(value)
    digits = dict(zip("零一二两三四五六七八九", (0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9)))
    total, digit = 0, 0
    for char in value:
        if char in digits:
            digit = digits[char]
        else:
            total += (digit or 1) * (10 if char == "十" else 100)
            digit = 0
    return total + digit


def generation_requested(question):
    """One authorization rule shared by routing and tool execution."""
    if re.search(NEGATED_GENERATION, question):
        return False
    return bool(re.search(EXAM_ACTION + r"|(?:生成|制作|准备|整理).*复习|复习提纲", question))


def topic_generation_intent(question):
    """Explicit topic generation never depends on a planner choosing search vs. create."""
    if not generation_requested(question) or re.search(r"错题|薄弱|复习计划|学习计划", question):
        return None
    exam = bool(re.search(EXAM_ACTION, question))
    topic = question
    # In "根据 X 出两道题，附解析", X is the topic; trailing requirements are not topics.
    before_action = re.match(
        rf"(?:请帮我|请为我|帮我|为我|给我|请)?\s*(?:根据|基于|针对|关于|围绕)\s*(.+?)\s*(?:生成|制作|准备|出(?=\s*(?:{NUMBER}|题|卷)))",
        question,
    )
    if before_action:
        topic = before_action[1]
    else:
        topic = re.split(r"[，,；;]\s*(?:并|附|带|含|给|提供|包含|要求)", topic, maxsplit=1)[0]
        topic = re.sub(rf"出(?=\s*(?:{NUMBER}|题|卷))", " ", topic)
        topic = re.sub(COUNT, " ", topic)
        topic = re.sub(
            r"请帮我|请为我|帮我|为我|给我|请|一下|根据|基于|针对|关于|围绕|生成|整理|制作|准备|"
            r"一份|一套|一张|复习资料|复习提纲|模拟试卷|模拟卷|模拟题|练习题|试卷|卷子|"
            r"题目|选择题|简答题|计算题|基础难度|简单|基础|中等难度|适中|高难度|困难|进阶",
            " ",
            topic,
        )
        topic = re.sub(r"^(?:再来|再给我|再|继续)\s*", "", topic.strip())
        topic = re.sub(r"题$", "", topic.strip())
    topic = re.sub(r"\s+", " ", topic).strip(' 的，。？！,:：?!"“”')
    whole_material = bool(re.search(r"每[章张]|各章|逐章|各个章节|每个章节|整本|全书|整份|全部资料", topic))
    topic = re.sub(r"^(?:上传的|当前|这份|这个|这本)?(?:教材|资料|课件|笔记)(?:中|里|内)(?:的)?", "", topic)
    topic = re.sub(r"^(?:这|该)(?=.{1,80}(?:这部分|部分|章节|一节))", "", topic)
    topic = re.sub(r"(?:这|该|这一)?(?:部分|章节|一节)(?:的)?(?:知识点|内容|重点)?$", "", topic)
    topic = re.sub(r"(?:的)?(?:知识点|相关知识|核心知识|知识内容)$", "", topic).strip(" 的，。 ")
    topic = re.sub(r"(?:给我|给)$", "", topic).strip()
    generic_material = bool(re.fullmatch(
        r"(?:上传的?|已上传的?|当前的?|选中的?|这些|这[个本份]|我的|全部的?)*"
        r"(?:pptx?|word|docx?|pdf|教材|资料|课件|笔记|书籍|书)(?:的?(?:重点|内容))?",
        topic,
        re.I,
    ))
    # Deictic requests need a topic; an arbitrary filler must not become a retrieval query.
    if whole_material or generic_material or topic in {
        "",
        "这个知识点",
        "这个",
        "这一知识点",
        "上述知识点",
        "该知识点",
        "它",
        "这个主题",
        "同一主题",
        "教材", "资料", "课件", "笔记", "这份资料", "这本书", "教材重点",
    }:
        topics = []
    else:
        topics = [
            item.strip(" 的 ") for item in re.split(r"[，,、；;]", topic) if item.strip(" 的 ")
        ]
    return (
        "generate_mock_exam" if exam else "generate_review",
        dict(
            topics=topics,
            question_count=(5 if re.search(r"试卷|卷子|一[张套份].*卷", question) else 3)
            if question_count(question) is None else question_count(question),
            question_type="choice"
            if "选择题" in question
            else "calculation"
            if "计算题" in question
            else "short_answer",
            difficulty="hard"
            if re.search(r"高难度|困难|进阶", question)
            else "easy"
            if re.search(r"简单|基础", question)
            else "medium",
        ),
    )


def study_intent(question):
    """Route explicit whole-material learning, independently of file format."""
    action = bool(
        re.search(
            r"提取|摘取|抽取|提炼|概括|整理|总结|归纳|梳理|生成|制作|准备", question
        )
        or re.search(EXAM_ACTION, question)
    )
    material = bool(
        re.search(
            r"资料|课件|笔记|教材|书籍|这本书|这[个本份].*书|整本|全书|pptx?|word|docx?|pdf",
            question,
            re.I,
        )
    )
    chapters = bool(re.search(r"每[章张]|各章|逐章|各个章节|每个章节", question))
    exam = bool(re.search(EXAM_ACTION + r"|复习卷|卷子", question))
    if re.search(NEGATED_GENERATION, question):
        exam = False
    knowledge = bool(
        re.search(
            r"重点|知识点|核心知识|提纲|内容|概念|提取|摘取|抽取|提炼|概括|总结|归纳|梳理", question
        )
    )
    if re.search(r"错题|薄弱|复习计划|学习计划", question):
        return None
    if not action or not (
        (material and (knowledge or exam)) or (chapters and knowledge) or "复习卷" in question
    ):
        return None
    named_topic = topic_generation_intent(question)
    if named_topic and named_topic[1]["topics"]:
        return None
    hint = re.search(r"(?:对于|针对|根据|基于)\s*(.+?)\s*这[个本份]", question)
    name = hint[1].strip() if hint else None
    if name and re.search(r"上传|当前|全部|选中|这些|我的", name):
        name = None
    return dict(
        document_name=name,
        question_count=question_count(question),
        question_type="choice"
        if "选择题" in question
        else "calculation"
        if "计算题" in question
        else "short_answer",
        include_questions=exam,
    )


def relation_intent(question):
    """Explicit bidirectional lookup; ordinary question searches keep their route."""
    materials = r"教材|资料|课件|ppt|word|pdf"
    exams = r"试卷|试题|题目|考题"
    if (
        not re.search(r"对应|关联|匹配|映射|联系", question)
        or not re.search(materials, question, re.I)
        or not re.search(exams, question)
    ):
        return None
    if re.search(r"生成|制作|出.*(?:卷|题)", question):
        return None
    query = re.sub(
        materials
        + "|"
        + exams
        + r"|对应|关联|匹配|映射|联系|查找|寻找|查看|知识点|我|的|请|一下|哪些|这个|这份|上传|当前|与|和|中|里|在",
        " ",
        question,
        flags=re.I,
    ).strip(" ，。？:：")
    return dict(
        direction="exam_to_material"
        if re.search(
            "(?:" + exams + r").*(?:对应|关联|匹配).*?(?:" + materials + ")", question, re.I
        )
        else "material_to_exam",
        query=query,
    )
