# 监督分类课程图谱与统一实训资产

本目录依照《课程个性化学习智能体项目搭建方案 v7》（本地源文档）建设知识图谱和课程资产模块。代码位于独立的 `learning-agent` 仓库，远端为 PLIAC。原 ChatEval 是参考来源，不能把本模块完成表述为整个平台首轮验收完成。

课程文件：[ml_classification.json](../data/courses/ml_classification.json)；实训资产：[training_blueprints.json](../data/training_blueprints.json)。

当前为版本 1：两章各 20 个节点，共 40 节点，其中 31 个核心节点、9 个拓展节点；68 条关系（54 条先修、5 条包含、8 条易混淆、1 条关联）；8 项概念资料出处、4 项补充课程资源候选、12 道诊断题草稿、3 个统一实训骨架（9 步、19 类错误）。节点、关系、诊断题、资源与实训骨架均为 `draft`，没有教师审核记录、真实学生记录或已运行实训结果。

## 对 v7 的落实与仍待完成的工作

| v7 定位 | 本次资产落实 | 尚待落实或核验 |
| --- | --- | --- |
| §1.4；附录 A.2 | 监督分类主线、数据划分、分类准确率、固定随机种子、分类树与深度对照；40节点、两个关联单元 | 教师确认章节名称、节点边界及先修顺序 |
| §3.2 | 明确前置、包含、关联、易混淆四类关系，保留出处、理由、版本和审核字段 | 教师逐项审核后才可转正式内容 |
| §1.2、§2.2、§3.2 | 资源候选记录机构、形态、适用片段、节点与前置；节点与诊断题及实训骨架关联 | 教师讲义、视频、案例及可运行实训尚未补齐，不能据四个网页声称每节点多形态材料完备 |
| §2.3、§3.2、§5.2 | 三份固定考核骨架，记录步骤、判定规格、错误归因和四级提示 | 教师提供或确认固定数据、阈值容差；隔离执行环境、判定脚本、过程采集与会话恢复尚未实现 |
| §1.3、§4.1、§4.4 | 诊断题有稳定 ID、版本、判据与四级提示；答案仅供教师/判定参考 | 独立/提示后作答、原话、版本和复核依据须由证据服务持续保存，不能靠答案关键词自动宣布掌握 |
| §2.4、§2.5 | 给出跨章先修与 `[1,7,30]` 天可配置复习间隔 | 达标条件、置信度变化和复测判据须按课程规则配置；间隔是首版规则示例，未做学习效果验证 |
| §5.5 | 结构数据可验证和追溯 | 未完成全部学习闭环、摄像头与后台回看、运行实训、2–3名真实学习者试跑等全平台验收项目 |

当前资产尚未接入教师课程大纲、教材页码及指定视频清单。公开官方页面仅作为补充候选与技术内容依据；“联网可访问”不等于“教师审核通过”。`reviewer` 与 `reviewed_at` 为空，`review_note` 写明待审核；不得自动补造审核人、日期或批准结论。

## 主线与节点范围

本课程主线是：识别分类任务和输入 → 按用途划分数据并固定随机设置 → 学习分类树 → 在固定条件下比较深度与训练/验证准确率 → 诊断欠拟合或过拟合 → 冻结选择 → 独立最终测试。

`ml037`—`ml040` 补充了分类准确率/错误率、固定随机种子、决策树分类和树深度复杂度。节点 ID 是稳定引用，不是教学顺序。原有线性回归和多项式例子已从课程主线说明中改为分类情境。

偏差、方差、L2、迭代损失曲线和早停等保留为 `scope: "extension"`，可作后续拓展；它们不是本轮分类树实训的必修条件。保留这些概念不表示教师已同意纳入首轮课程。

### 监督分类的数据划分与评估

| ID | 知识点 | 范围 |
| --- | --- | --- |
| `ml001` | 监督分类任务 | 核心 |
| `ml002` | 样本、特征与标签 | 核心 |
| `ml003` | 模型与预测 | 核心 |
| `ml004` | 参数与模型拟合 | 核心 |
| `ml005` | 数据划分方案 | 核心 |
| `ml006` | 训练集 | 核心 |
| `ml007` | 训练表现与训练误差 | 核心 |
| `ml008` | 验证集 | 核心 |
| `ml009` | 超参数 | 核心 |
| `ml010` | 模型选择 | 核心 |
| `ml011` | 测试集 | 核心 |
| `ml012` | 泛化与泛化误差 | 核心 |
| `ml013` | 数据代表性 | 核心 |
| `ml014` | 数据泄漏 | 核心 |
| `ml015` | 预处理的拟合边界 | 核心 |
| `ml016` | 交叉验证 | 核心 |
| `ml017` | 分层划分 | 核心 |
| `ml018` | 分组与时间划分 | 核心 |
| `ml037` | 分类准确率与错误率 | 核心 |
| `ml038` | 固定随机种子与划分复现 | 核心 |

### 决策树复杂度与欠拟合、过拟合

| ID | 知识点 | 范围 |
| --- | --- | --- |
| `ml019` | 模型复杂度 | 核心 |
| `ml020` | 欠拟合 | 核心 |
| `ml021` | 过拟合 | 核心 |
| `ml022` | 训练与验证差距 | 核心 |
| `ml023` | 偏差 | 拓展（不作为分类树主线门槛） |
| `ml024` | 方差 | 拓展（不作为分类树主线门槛） |
| `ml025` | 偏差与方差的权衡 | 拓展（不作为分类树主线门槛） |
| `ml026` | 验证曲线 | 核心 |
| `ml027` | 样本量学习曲线 | 核心 |
| `ml028` | 训练过程损失曲线 | 拓展（不作为分类树主线门槛） |
| `ml029` | 增加数据的适用条件 | 核心 |
| `ml030` | 正则化 | 拓展（不作为分类树主线门槛） |
| `ml031` | L2惩罚项 | 拓展（不作为分类树主线门槛） |
| `ml032` | 正则化强度 | 拓展（不作为分类树主线门槛） |
| `ml033` | 一致预处理与正则化实验 | 拓展（不作为分类树主线门槛） |
| `ml034` | 早停 | 拓展（不作为分类树主线门槛） |
| `ml035` | 诊断证据与对照实验 | 核心 |
| `ml036` | 选择完成后的独立评估 | 核心 |
| `ml039` | 决策树分类 | 核心 |
| `ml040` | 树深度与复杂度控制 | 核心 |

## 关系与学习状态语义

- `prerequisite: A → B` 表示课程编排建议先理解 A 再学习 B；只有此类型约束学习顺序。先修子图无环。图中顺序是待教师审核的编排，不是来源作者批准的先修研究结论。
- `contains: A → B` 表示概念范围包含；`related` 是一般关联；`confusable` 是需要专门辨析的易混淆概念。后两类的存储端点不表示学习顺序。包含、关联、易混淆边都不能自动成为解锁条件。
- 训练/验证/测试、参数/超参数、欠拟合/过拟合等以 `confusable` 明确呈现。不能把“相关”当成“必须先学”。
- 典型跨章连接包括验证集 → 过拟合、分类准确率 → 训练/验证差距、模型选择 → 验证曲线。目标暴露问题时回查相关前置证据，不凭后继答错宣布全部前置不会。
- 课程图谱与学生状态分离。绿色表示当前证据支持掌握，红色表示需要补学，灰色表示尚未涉及，黄色表示已经涉及但证据不足或冲突。技术错误、未作答和表情/停顿不能直接判为不会。
- 已掌握可跳过当次补学，但并非永久免于核验；按最近支持掌握的时间、复习间隔和新证据决定是否简短复测。`review_policy.intervals_days` 的默认 1、7、30 天来自 v7 的首版示例，允许课程侧修改。

## 概念出处与资源候选

`sources` 保留 8 项原有技术出处，用于说明概念背景；`resources` 独立存储 4 项可以审核为补充学习材料的候选。节点的 `source_ids` 指向背景出处，`resource_ids` 指向更具体的教学页面，例如新决策树节点指向 `res_tree`。两者均不能冒充教师课程材料。

2026-10-08 已联网打开并核对相关页面；内容均以原创中文概括，并未复制完整教材。原有出处如下：

- `google_supervised`：[Google：Supervised Learning](https://developers.google.com/machine-learning/intro-to-ml/supervised)
- `google_split`：[Google：Datasets — Dividing the original dataset](https://developers.google.com/machine-learning/crash-course/overfitting/dividing-datasets)
- `sklearn_cv`：[scikit-learn：Cross-validation — evaluating estimator performance](https://scikit-learn.org/stable/modules/cross_validation.html)
- `sklearn_pitfalls`：[scikit-learn：Common pitfalls and recommended practices](https://scikit-learn.org/stable/common_pitfalls.html)
- `google_overfit`：[Google：Overfitting](https://developers.google.com/machine-learning/crash-course/overfitting/overfitting)
- `google_l2`：[Google：Overfitting — L2 regularization](https://developers.google.com/machine-learning/crash-course/overfitting/regularization)
- `sklearn_curves`：[scikit-learn：Validation curves and learning curves](https://scikit-learn.org/stable/modules/learning_curve.html)
- `google_loss_curves`：[Google：Overfitting — Interpreting loss curves](https://developers.google.com/machine-learning/crash-course/overfitting/interpreting-loss-curves)

候选资源如下，完整节点与前置映射在 JSON 中。当前四项均为文字课节，未填入未经核验的视频链接；后续可用教师审核的视频或课程条目替换。

| ID | 候选资源 | 机构 | 形态 | 适用片段 |
| --- | --- | --- | --- | --- |
| `res_split` | [数据集如何分为训练、验证和测试集](https://developers.google.com/machine-learning/crash-course/overfitting/dividing-datasets) | Google | lesson | Training, validation, and test sets；Additional problems with test sets。重点讨论三类用途、重复样本和评估边界；固定种子的技术依据另见 sources 中 sklearn_cv。 |
| `res_accuracy` | [分类准确率及其适用边界](https://developers.google.com/machine-learning/crash-course/classification/accuracy-precision-recall) | Google | lesson | Accuracy 段落及类别不均衡示例；Choice of metric and tradeoffs 作为延伸阅读。本次不要求精确率、召回率公式。 |
| `res_tree` | [决策树分类与复杂度控制](https://scikit-learn.org/stable/modules/tree.html) | scikit-learn 开发团队 | lesson | 1.10 开头的过拟合与复杂度说明；1.10.1 Classification；1.10.5 Tips on practical use。以分类、max_depth 和叶节点限制为主，不采用回归示例作主线。 |
| `res_pitfalls` | [预处理一致性与数据泄漏](https://scikit-learn.org/stable/common_pitfalls.html) | scikit-learn 开发团队 | lesson | 12.1 Inconsistent preprocessing；12.2 Data leakage。阅读训练部分 fit、留出部分 transform 和 Pipeline 的边界。 |

固定种子节点主要依据 `sklearn_cv` 的 `random_state` 说明；实现时还可查阅 [train_test_split 官方参数说明](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.train_test_split.html)。固定种子不等于无泄漏或评估无偏，数据版本、顺序及其他配置同样需要保存。

## 诊断题、评分依据与受控提示

12 个节点带有 `check_question`、教师侧 `expected_answer` 和结构化 `check_task`。每个任务有稳定 ID、版本、两条观察判据及四级提示；节点 `task_ids` 指向这些任务。判据用于复核具体回答，不是已经验证的能力量表，也没有任意统一分数阈值。

四级提示按“指出检查位置 → 引导问题 → 相关概念 → 关键要点”递进。学习者可看到当前允许的提示，不能在作答前直接得到 `expected_answer`。保存原始回答、任务和节点版本、提示等级与判断依据；独立正确、提示后正确、反复修改后正确应保留区别。分级提示不改变统一判据。

讲解阶段可以完整说明概念；检验阶段优先追问。开放题不是实训自动判定脚本，不能靠 LLM 自报“正确”替代原始证据和复核。

## 三个统一实训骨架

三份骨架根及每条资产均标为 `runtime_status: "not_implemented"`。它们是课程设计资产，尚无 Docker 环境、运行脚本、真实执行记录或自动验收结果。

| ID | 固定考核内容 | 客观判定规格 | 待课程侧确定 |
| --- | --- | --- | --- |
| `bp_split` | 三份样本清单；固定随机配置复现；预处理拟合边界 | ID互斥与覆盖、数量规则、复现结果一致、fit来源只含训练样本 | 数据版本、比例与取整、分层策略、随机配置、预处理规格 |
| `bp_tree_diagnosis` | 深度候选对照；训练/验证准确率；拟合判断；验证选优 | 候选覆盖、固定条件、指标复算、现象标签和选优容差 | 深度网格、固定参数、现象校准规则、期望范围、数值容差与并列选择规则 |
| `bp_final_evaluation` | 冻结方案；一次独立测试；证据化报告 | 模型摘要一致、测试事件顺序、结果复算、报告可追溯 | 测试清单、重拟合策略、报告字段及事件来源契约 |

每一步都有 `judge_spec`、错误类型引用和四条分级提示。每类错误关联具体知识节点、典型误解和引导话术。判定器的目标是执行已批准规则，不能临时让模型编造规则或阈值。

`judge_spec.parameters_required` 列出未给定的参数。参数缺失时应返回配置未就绪，而非判学生不通过。环境故障记录为技术问题，并允许在同一检查点重试；不得据此降低学生能力判断。最终测试的“一次”指在冻结方案后独立揭示结果；尚未产生结果的技术失败不能当成学生额外调参或能力不足。

情境只可更换剧情、角色、展示特征名和展示文件名。统一数据的规模、分布、数值、标签、难度、考核步骤和判定规则均不变；映射必须一一对应。兴趣仅决定外观。情境生成后须做一致性校验，不把实例回写为骨架。

## 内容审核与验收边界

1. 教师确认首轮课程目标、章节划分、节点颗粒度与每条先修/易混淆关系。
2. 接入教师大纲、教材、课件与题目；审核资源的适用片段和先修要求，再将候选转为正式资源。
3. 为每个实训提供批准的数据版本、参数与校准结果，复核错误类型、提示和判定规格。
4. 增加与节点对应的教案、案例与视频，记录学生实际选择及推荐理由。
5. 后续实现运行环境、判定脚本、证据采集、状态更新、知识手册与章节评价闭环，并安排真实学习者试跑。
6. 只有实际人工审核后才改为 `reviewed`，同时记录审核人、日期、说明和新版本；结构校验不自动授予审核状态。

本次结构验证覆盖 JSON 可解析、ID唯一、节点/来源/资源/任务/骨架引用、四类边、两章40节点、先修无环、全图连通、诊断提示与骨架错误映射。它验证的是资产结构，不证明课程有效性、运行实训正确性或全平台验收完成。
