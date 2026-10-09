# 统一课程运行路径

课程列表全部来自 `/api/courses`，统一返回 `presentation`、统计值和 `capabilities`，前端只有一个卡片模板。学习端统一使用 `LearningWorkspace`；段落、题目选项、复测题、学习顺序、混合练习和活动入口由课程数据决定，不判断课程名称或 ID。

运行时创建或从资料生成的课程仍使用 `CourseGraphStore`，保留草稿、人工审核与发布规则。固定版本的预装内容通过 `data/courses/<目录>/package.json` 自动发现，使用通用 `PackagedCourseStore` 适配存储；`acceptance_course.py` 和 `textbook_demo.py` 只保留旧导入兼容入口。它们不再拥有课程行为实现。

## 数据位置

- `graph`：同一种课程图谱结构，节点可携带 `lesson_content`、`check_task.options` 和 `retest_tasks`。普通文字题仍支持旧的 `check_question` 字段。
- `presentation`：卡片说明及来源标签。节点、章节和关系统计实时从图谱计算。
- `activities`：已有实验引擎、入口、关联段落、知识点映射；实验继续遵守各自的执行契约。新课程可以绑定已有实验，不会因为改了课程名就切换算法。
- `study.mixed_tasks` / `study.load_profiles`：混合练习及有依据的内容负荷估计。答案只在服务端保留；公开课程数据不返回 `study`。
- `handouts` / `source_snapshot`：可选的预装讲义和归档原文。预装与生成任务共用 LearnMargin 存储、生成入口及阅读器。
- `runtime_path`：固定版本的独立学习记录位置。已有机器学习和计组记录路径保持不变。
- `assessment`：受版本控制的评分契约。既有 ML 验收数据保留 `demo-choice-v1`；普通课程不会仅凭选项或模型输出自动获得掌握诊断。

## 验证边界

`test_unified_courses.py` 用陌生课程 ID、改名的知识点、植物学段落与练习验证公共流程，同时检查实验记录不串课程、答案不外泄、预装与生成讲义共存。生成调度测试使用模型替身；真实 HTML/PDF 渲染和图谱生成审校契约由现有 LearnMargin 测试覆盖。原始教材历史候选图谱仍保留来源标识，不冒充新管线生成或人工审核结果。
