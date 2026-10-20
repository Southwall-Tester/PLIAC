# 常驻学习助手与动态画像

课程列表、资料大图、课程图谱、讲义、学习工作区和两个 Lab 都提供右侧学习助手。桌面默认展开，支持收起及 Ctrl+J；手机使用抽屉。跨页面保留对话、输入草稿及后台回答，支持新对话、历史记录、停止和重试。

可直接提问一般问题，也可以围绕当前课程、选中知识点、讲义或选中文字提问。回答下方提供相关材料与历史记忆入口。平台复用服务端环境变量或可选 `config/models.json` 中的模型、协议和请求控制。聊天、基础核验分析与学习内容准备会按实际操作调用模型。当前返回完整回答。

0.12 起先登录再进入课程。账号分别持有固定的学习者编号与助手记忆空间；服务器校验会话身份，跨浏览器登录同一账号可恢复已保存对话和画像。首次课程自评、基础核验与路线流程见 [个性化学习流程](personalized-learning-flow.md)。

## 画像怎样形成、怎样改变回答

1. **原始表达**：保存用户消息、当前页面定位及时间。用户消息和助手消息保持各自身份。
2. **有依据的抽取**：模型输出结构化的学习目标、兴趣、知识背景、讲解偏好。每条条目必须引用本次用户原话中的连续片段；程序逐字检查引用。
3. **增量更新**：按类别和偏好槽合并；新明确表达覆盖旧表达，推测不能覆盖明确偏好，用户手动修正优先。旧值保留为历史版本。
4. **长短期加权**：兴趣半衰期 30 天；明确偏好 180 天；推测偏好 45 天。基础权重为手动修正 1、明确表达 0.9、推测 0.45。重复观察增加有限支持。这里是检索优先级的工程初值，后续可据交互评测校准。
5. **按问题检索**：中文双字词和英文词使用 BM25；优先级为 `时间衰减权重 × (1 + BM25相关度)`。选取最多 8 项相关画像，讲解偏好和当前目标可跨话题复用。
6. **用于生成**：将选中的画像与当前问题一起传入模型，使讲解详略、步骤、例子主题与核验难度发生变化；每个回答记录用了哪些画像条目。
7. **用户控制**：右上角“记忆”可以查看画像和任务记录、依据、原对话，修改、删除，以及关闭个性化。删除的条目登记抑制标识，防止旧对话被再次提取。回答生成期间发生的画像修正优先于该次旧快照。

兴趣和背景使用多条自然语言条目，讲解偏好使用 detail、format、pace、language、examples、tone 六个槽。当前学习目标独立保存。画像关注学习信息，不抽取健康、政治宗教等个人敏感属性。

## 判断卡点与调整教学

当前页面定位和 BM25 共同检索知识点、定义、常见误解、核验题与参考答案。只有图谱明确标注的 prerequisite 进入先修候选。

模型对学习者本次表达给出 misconception、partial、correct、question 四类信号，分别呈现为“发现理解偏差”“需要补全推理”“本轮解释清楚”“正在核验”，同时给出理由与一条下一步核验问题。程序检查概念编号、来源编号及用户原话引用，接收可定位的诊断。下一轮按当前课程取回最近知识点表现，用于调整解释及练习。

普通问题、兴趣、点击和求助次数分别处理。聊天诊断作为模型判断保存；正式课程的证据、复核和掌握状态继续走共享学习记录原有契约。画像层提供适应性教学上下文，课程层保留可审核的掌握结论。

## 研究依据与本项目采用方式

| 来源 | 公开方法 | 本项目落点 |
| --- | --- | --- |
| [User Modeling in the Era of Large Language Models](https://arxiv.org/abs/2312.11518) | 从文本及交互建模用户，用于理解和个性化 | 学习目标、兴趣、背景与回答偏好分维度存储 |
| [Understanding the Role of User Profile](https://arxiv.org/abs/2406.17803) | 分析画像信息对个性化生成的作用 | 测试画像确实进入后续请求，并检查回答的变化 |
| [Dynamic Profile Modeling / RLPA](https://arxiv.org/html/2505.15456v1) | 联合考虑动态画像更新与个性化回答 | 每轮提取、冲突消解、下一轮重用；采用工程更新规则，未训练 RLPA |
| [Toward Personalized LLM-Powered Agents](https://arxiv.org/abs/2602.22680) | 从用户建模、记忆与智能体流程讨论个性化 | 对话、画像、检索和回答策略分层实现 |
| [The Algorithmic Self-Portrait](https://research.tudelft.nl/en/publications/the-algorithmic-self-portrait-deconstructing-memory-in-chatgpt/) | 研究真实 ChatGPT 记忆的来源、推断及用户能动性 | 每条画像提供原话依据、编辑与删除入口 |
| [OpenAI：Codex development workflows](https://developers.openai.com/cookbook/examples/codex/iterating-development-workflows-with-codex)；[Sandbox memory](https://developers.openai.com/api/docs/guides/agents/sandboxes) | 持久指导、过程记忆与会话历史分开保存，按需检索 | 原始对话、抽取证据、当前画像分文件保存 |
| [Netflix 推荐系统说明](https://help.netflix.com/en/node/100639/) | 使用交互、反馈和内容特征并随新行为更新 | 兴趣与当前任务独立建模；兴趣用于例子和推荐语境 |
| [Amazon Personalize 实时更新](https://docs.aws.amazon.com/personalize/latest/dg/how-new-data-influences-recommendations.html)；[Shopping Intents](https://arxiv.org/abs/2305.05279) | 最新交互与任务意图改善实时推荐 | 区分当前目标和长期偏好，并在下一次回答中生效 |
| [Amazon：可编辑自然语言画像](https://www.amazon.science/publications/enabling-user-agency-in-scalable-content-recommendations-with-large-language-models) | 可解释、可编辑、带权重的自然语言偏好 | 可查看修正的条目及透明检索权重 |
| [Misconception Diagnosis: Generate, Retrieve, Rerank](https://arxiv.org/html/2602.02414v1) | 误解候选生成、检索及重排 | 课程误解候选检索、模型语义判断、引用校验；本实现采用 BM25 和现有模型 |
| [Training LLM-based Tutors](https://arxiv.org/html/2503.06424v2) | 准确性、进展和引导的教学评价与学生响应预测 | 根据前轮表现调整解释、每轮提供可执行核验题；本实现未进行 DPO 训练 |
| [Tutor CoPilot](https://arxiv.org/abs/2410.03017) | 向真人导师提供教学策略建议，并进行课堂随机试验 | 借鉴针对性解释、引导问题和下一步行动；该论文的课堂效果不等于本项目效果 |

上述产品和论文提供机制依据；本项目组合的是可在现有规模运行的可解释基线。时间衰减参数、检索数量和信号标签由本项目定义，验证记录区分结构测试、模型样例和课堂效果。

## Hy Memory 与 REMORY 的集成取舍

[Hy-Memory 官方仓库](https://github.com/Tencent-Hunyuan/Hy-Memory) 将原始对话、原子事实、摘要和用户画像分层组织，提供场景及来源隔离、更新和删除。PLIAC 采用同类分层方法：原始对话保持独立，任务摘要只保存来源定位；工作、代码、学习、一般交流记录分域，检索时按账号和课程/文档范围过滤。任务摘要记录目标、决策或可复用经验，原话逐字校验；修订通过 `supersedes` 关联旧版本，用户修改优先于模型自动更新。当前为本地实现，未引入 Hy-Memory SDK 或下载 Hy-Memory-30B-A3B 权重。

模型返回空记忆或原话引用无效时，这轮交流仅保留在原会话，不进入跨会话的长期记忆索引。长期记忆筛选与原始聊天记录分别处理。

[REMORY 论文](https://arxiv.org/abs/2610.11287) 训练记忆网络，将残差信息编码为有界软 token，补充文本摘要，Actor 保持冻结。PLIAC 借鉴“摘要保主线、原始细节补遗漏”的结构：近期完整轮次、相关任务摘要、原话检索三路共同构成上下文。原话检索可命中摘要未包含的命令、路径、参数，保留用户/助手角色与时间。当前实现使用文本 API 和 BM25；神经软 token 实现需要匹配的 Actor、记忆网络及支持隐藏状态/连续向量的推理运行时。

上下文历史部分按实际 JSON 字符计量，近期轮次预算 18,000、摘要 3,000、原文片段 6,000，合并硬上限 28,000 字符（含结构开销，课程引用与系统提示另计）。最新完整用户输入始终保留；一条过长助手回答不会让历史选择变成空列表。索引最多保留 600 条，原始对话保留在各自会话文件。删除和修订抑制标记会阻止旧记录重新进入短期上下文与历史检索。工程阈值为当前基线，字符数不等同于模型 token 数。

REMORY 作者提供了 [第三方 Codex 适配器](https://github.com/fudan-generative-vision/Remory/blob/main/integrations/codex/README.md)，将原生 Codex UI 连接到其本地推理服务。[OpenAI 公开 compaction 文档](https://developers.openai.com/api/docs/guides/compaction) 没有确认内部采用 REMORY；不能据第三方适配推断 ChatGPT/Codex 的内部算法。

## 数据与运行

数据位于 `outputs/course_graph/assistant/<账号助手身份>/`：

- `<会话编号>.json`：原始对话、页面定位及回答记录。
- `profile/current.json`：当前画像、修订号、条目历史和派生知识点表现。
- `profile/evidence/<消息编号>.json`：画像来源与逐轮诊断。
- `memory/current.json`：任务摘要、原话定位、修订链与删除抑制标记。

浏览器按账号分别保存活动会话编号、面板开关和未发送草稿。正式会话身份由 HttpOnly Cookie 和服务器账号表决定；旧匿名记录保留，注册账号时不自动认领。模型凭证由服务端配置读取。

```powershell
python -X utf8 -m unittest discover -s tests -p "test_assistant.py"
python -X utf8 -m unittest discover -s tests -p "test_assistant_memory.py"
python -X utf8 tests/test_ui_assistant.py
python -X utf8 scripts/verify_personalized_journey.py
```
