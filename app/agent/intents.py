import re


def study_intent(question):
    """Route explicit whole-material learning, independently of file format."""
    action = bool(
        re.search(
            r"提取|摘取|抽取|提炼|概括|整理|总结|归纳|梳理|生成|制作|准备|出.*(?:卷|题)", question
        )
    )
    material = bool(
        re.search(
            r"资料|课件|笔记|教材|书籍|这本书|这[个本份].*书|整本|全书|pptx?|word|docx?|pdf",
            question,
            re.I,
        )
    )
    chapters = bool(re.search(r"每[章张]|各章|逐章|各个章节|每个章节", question))
    exam = bool(re.search(r"复习卷|卷子|(?:生成|制作|出|准备).*(?:卷|题)", question))
    if re.search(r"(?:不要|不用|不需要|无需|不必).{0,5}(?:出题|出卷|试卷|练习题|复习卷)", question):
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
    count = re.search(r"(\d+)\s*(?:道|题)", question)
    hint = re.search(r"(?:对于|针对|根据|基于)\s*(.+?)\s*这[个本份]", question)
    name = hint[1].strip() if hint else None
    if name and re.search(r"上传|当前|全部|选中|这些|我的", name):
        name = None
    return dict(
        document_name=name,
        question_count=int(count[1]) if count else None,
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
