# LearnMargin 课程接入

PLIAC 复用 LearnMargin 的规划、章节生成、审校、负荷休息规划和离线 HTML/PDF 排版。上游来源为 https://github.com/Southwall-Tester/LearnMargin ，快照 `63dba8f37ce17ff59c41765264beba07c9cf0ea1`（0.2.1），许可见 [MIT 授权](third-party/LearnMargin-LICENSE.txt)。源代码保留在 `src/learnmargin`；只保留生成与排版依赖及共享方法参考，没有接入上游独立 Web 应用、上传入口或任务库。

2026-10-10 选择性同步 [v0.3.0 / `49f1f5e5f9cdad05d30982978f715f399416559f`](https://github.com/Southwall-Tester/LearnMargin/commit/49f1f5e5f9cdad05d30982978f715f399416559f) 的模型思考参数、请求 token 字段和超时诊断，并将失败阶段记录移植到 PLIAC 任务层。`reasoning.py` 保留上游能力表；`provider.py` 的超时文案按课程入口调整，不承诺尚未接入的扫描页续读。没有升级整个核心：逐页多模态缓存、转录优先的图片规划、上游 Web 应用和独立 Skill 更新均未引入。原快照已包含自动分章、内容相邻侧栏和生成核心安全加固。新任务元数据记录 `LearnMargin 63dba8f + model controls 49f1f5e`；历史产物不改写。

## 数据流

课程列表 → `/course-reader?course_id=...` → `/api/handouts` → 课程已有资料快照 → LearnMargin 完整生成与审校 → 概念及语义关系提取 → HTML/PDF → 图谱节点定位讲义。

`src/pliac/margin.py` 将课程已有 `lesson_content` 等教学材料转换为 SourceUnit。已导入教材通过节点的 `document_id` 与 `document_evidence.page` 读取完整缓存页，不能把图谱里的短引文当完整资料。只读当前课程及所选章节明确关联的资料，不扫描或发送其他课程的上传文件。PDF 页和 Word 原文段分别标识。范围过大时明确要求选现有章节，不静默截断。

资料、课程版本、生成章节和图谱保存在对应课程输出目录的 `handouts` 中；未修改固定 v1 课程、原始作答或掌握诊断。草稿资料生成结果保留 `source_view=draft`，生成不会把课程发布或制造教师审核。原材料回查读取本次任务快照，可打开仍在课程中的原文件。

`src/pliac/margin_graph.py` 采用 `concept-first-v3`（v3 相对 v2：关系谓词须使用讲义语言的简短动词短语；新任务在 job 中记录 `generator.model` 与策略版本）：先提取带学科类型的原文术语表，再单独审查原子性和学科术语资格，程序据布尔审查决定移除不合格项；最后只把获准术语交给关系生成阶段。关系不能恢复被拒节点。审核决定与规则版本随图谱保存，回归覆盖不同学科。根据完整讲义提取独立概念和语义关系，不按目录顺序自动连线。模型选择程序编号的原文段落，程序补入原文与来源；校验节点、小节、关系端点及段落引用。该校验能保证引用可定位，不能替代学科专家对关系含义的审核。

## 使用与配置

### 独立学习范围

`learning_scope.py` 为整课、章节、原文目录单元、课程知识点和已生成图谱的概念提供统一范围契约。`chapter_id / section_id / node_id` 从课程数据解析；`source_job_id + concept_id` 从该课程已完成的图谱和材料快照解析。客户端不能指定任意原文引用或文件路径。目录单元按真实层级及成员关系选择知识点；带 `source_ranges` 的章节读取声明的完整页码范围，其余范围读取所属知识点明确关联的完整原文页或教学段落。跨范围的前置知识另列入口，不自动并入单元。

`POST /api/handouts` 接受 `{ "scope": { ... } }`；旧的 `chapter_id` 请求仍兼容。稳定范围键隔离并发任务、历史版本和失败恢复；课程版本及资料快照还须一致才能续作。每个新单元须包含可作答练习，再复用同一图谱审核和 HTML/PDF 管线。材料超过生成容量时提示缩小范围，不截断冒充全章完成。

`GET/POST /api/handouts/{job_id}/practice` 通过 `handout_practice.py` 读写共享 learner store，支持草稿、提示、参考答案和原始作答。写入带乐观版本与幂等请求编号；范围、任务、题目和来源保存在证据上下文中，提示暴露随尝试保留。生成习题不自动绑定已审核的课程测评，也不创建掌握诊断。换单元、换版本或重新生成均保留已有作答。

阅读器提供上级入口和历史版本切换。“下载 PDF”只在讲义内容区出现，图谱和练习视图不显示该按钮。

`pip install -r requirements.txt` 后安装浏览器：`python -m playwright install chromium`。现有课程模型配置 `config/models.json` 优先；没有文件时沿用 `LEARNMARGIN_BASE_URL`、`LEARNMARGIN_MODEL`、`LEARNMARGIN_API_KEY` / `DEEPSEEK_API_KEY` 的上游规则。用户在课程内只选择已有章节、生成或取消，无需重新输入材料。

模型项现在接收 `protocol`、`reasoning_effort`、`timeout_seconds`、`vision` 和 `json_mode`，示例见 `config/models.example.json`。不填写思考档位或设置为 JSON `null` 表示使用服务默认行为，不发送思考参数；这与旧代码隐式关闭 DeepSeek 思考不同，可能改变耗时和费用。DeepSeek 已登记的官方模型可用 `"none"` 明确关闭，或选择 `"low"`、`"high"`、`"max"`。其他模型可用选项来自 `src/learnmargin/reasoning.py`，按规范化服务地址、协议和完整模型 ID 匹配；未知网关或模型只能不指定，不猜测转发服务能力。不支持的显式设置会在发送请求前给出中文配置错误，不自动降级或更换模型。能力表来源与边界见[上游适配说明](https://github.com/Southwall-Tester/LearnMargin/blob/49f1f5e5f9cdad05d30982978f715f399416559f/docs/REASONING.md)。

没有配置文件时，可设置 `LEARNMARGIN_REASONING_EFFORT`（省略或空值表示不指定）和 `LEARNMARGIN_TIMEOUT_SECONDS`。超时默认 180 秒，可设 10～600 秒，约束单次请求及其重试和响应读取，不是整份讲义总时限。有配置文件时，以文件选中的模型项为准。这些设置用于课程讲义及其概念图谱共用的 LearnMargin Provider，不改变旧资料候选提取模块的调用方式。

启动入口检查 `scoped_learning_units` 能力，避免复用不支持独立学习单元接口的旧服务。首次生成调用模型，完成后再次打开直接读取已保存讲义。失败时已完成讲义作为检查点保存；相同资料的图谱失败可重试剩余阶段。重新生成不会覆盖既有成品或学习记录。

任务失败时保留 `failed_stage`，阅读器直接显示“阶段：原因”，例如“生成知识概念及关系：模型响应超时……”。重新执行任务会清除旧失败阶段与错误；已有讲义检查点仍按原规则复用。配置或代码更新后需重启后端，单独刷新页面不会更新进程内代码。

## 验证

`tests/test_margin.py` 检查课程范围、完整原文、跨课程资料隔离、可定位图谱依据与真实 LearnMargin PDF 排版。`test_learning_scopes.py` 检查范围与练习的资料隔离、幂等、冲突和证据边界；`test_ui_learning_scopes.py` 使用合成模型输出走通章节、知识点、图谱概念的真实生成与排版、版本切换、练习保存、刷新恢复和移动端 PDF 下载入口。测试夹具中的模型替身用于验证链路，不能冒充真实模型生成或学习效果。

当前源代码适配点：生成系统约束要求面向读者使用自然语言字段名称，侧栏模板隐藏内部提示 ID；PLIAC 适配层对提示中的内部字段引用做显示名称转换。保留原始模型章节检查点。

`tests/test_margin_model_controls.py` 覆盖配置文件与环境变量、非法档位及超时、请求参数与连接测试、失败阶段持久化及检查点重试；使用本地模拟 HTTP，不调用付费模型。可运行 `python -X utf8 -m unittest discover -s tests -p "test_margin*.py"`，并运行 `python -X utf8 tests/test_ui_learning_scopes.py` 验证课程阅读器、生成失败提示和原有学习记录流程。
