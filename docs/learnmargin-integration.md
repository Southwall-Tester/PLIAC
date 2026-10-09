# LearnMargin 课程接入

PLIAC 复用 LearnMargin 的规划、章节生成、审校、负荷休息规划和离线 HTML/PDF 排版。上游来源为 https://github.com/Southwall-Tester/LearnMargin ，快照 `63dba8f37ce17ff59c41765264beba07c9cf0ea1`（0.2.1），许可见 [MIT 授权](third-party/LearnMargin-LICENSE.txt)。源代码保留在 `src/learnmargin`；只保留生成与排版依赖及共享方法参考，没有接入上游独立 Web 应用、上传入口或任务库。

## 数据流

课程列表 → `/course-reader?course_id=...` → `/api/handouts` → 课程已有资料快照 → LearnMargin 完整生成与审校 → 概念及语义关系提取 → HTML/PDF → 图谱节点定位讲义。

`src/pliac/margin.py` 将课程已有 `lesson_content` 等教学材料转换为 SourceUnit。已导入教材通过节点的 `document_id` 与 `document_evidence.page` 读取完整缓存页，不能把图谱里的短引文当完整资料。只读当前课程及所选章节明确关联的资料，不扫描或发送其他课程的上传文件。PDF 页和 Word 原文段分别标识。范围过大时明确要求选现有章节，不静默截断。

资料、课程版本、生成章节和图谱保存在对应课程输出目录的 `handouts` 中；未修改固定 v1 课程、原始作答或掌握诊断。草稿资料生成结果保留 `source_view=draft`，生成不会把课程发布或制造教师审核。原材料回查读取本次任务快照，可打开仍在课程中的原文件。

`src/pliac/margin_graph.py` 采用 `concept-first-v2`：先提取带学科类型的原文术语表，再单独审查原子性和学科术语资格，程序据布尔审查决定移除不合格项；最后只把获准术语交给关系生成阶段。关系不能恢复被拒节点。审核决定与规则版本随图谱保存，回归覆盖不同学科。根据完整讲义提取独立概念和语义关系，不按目录顺序自动连线。模型选择程序编号的原文段落，程序补入原文与来源；校验节点、小节、关系端点及段落引用。该校验能保证引用可定位，不能替代学科专家对关系含义的审核。

## 使用与配置

`pip install -r requirements.txt` 后安装浏览器：`python -m playwright install chromium`。现有课程模型配置 `config/models.json` 优先；没有文件时沿用 `LEARNMARGIN_BASE_URL`、`LEARNMARGIN_MODEL`、`LEARNMARGIN_API_KEY` / `DEEPSEEK_API_KEY` 的上游规则。用户在课程内只选择已有章节、生成或取消，无需重新输入材料。

启动入口检查 `learnmargin_graph` 能力，避免复用不支持讲义接口的旧服务。首次生成调用模型，完成后再次打开直接读取已保存讲义。失败时已完成讲义作为检查点保存；相同资料的图谱失败可重试剩余阶段。重新生成不会覆盖既有成品或学习记录。

## 验证

`tests/test_margin.py` 检查课程范围、完整原文、跨课程资料隔离、可定位图谱依据与真实 LearnMargin PDF 排版。浏览器验收覆盖课程入口、概念到讲义跳转、来源弹窗返回、PDF、手机和已有课程实验回归。测试夹具中的模型替身用于验证链路，不能冒充真实模型生成或学习效果。

当前源代码适配点：生成系统约束要求面向读者使用自然语言字段名称，侧栏模板隐藏内部提示 ID；PLIAC 适配层对提示中的内部字段引用做显示名称转换。保留原始模型章节检查点。
