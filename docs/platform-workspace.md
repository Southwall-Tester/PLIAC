# PLIAC 学习工作台接入说明

依据本地 v7（2026-10-08）方案正文与附录，沿 PLIAC 的 `main` 新建 `feat/learning-workspace`。没有创建 fork，也没有修改 ChatEval 原仓库。本轮保留已完成的知识图谱作为平台模块，继续建设学习交互与人工复核链路。

## 模块与入口

### 独立验证图谱版本

图谱无需始终占据 main。`feat/knowledge-graph` 分支供单独验证或后续维护；`knowledge-graph-v0.4.2` 标签固定本轮平台开发之前的代码。精确提交为 [`02aacf1b8a442f168e146f83e0e72cb27f0033bb`](https://github.com/Southwall-Tester/PLIAC/commit/02aacf1b8a442f168e146f83e0e72cb27f0033bb)。分支后续可以向前推进，复现报告应记录完整 SHA。

首次取代码：

```powershell
git clone --branch knowledge-graph-v0.4.2 https://github.com/Southwall-Tester/PLIAC.git PLIAC-graph
cd PLIAC-graph
git rev-parse HEAD
pip install -r requirements-dev.txt
python -m unittest discover -s tests -p "test_*.py"
python scripts/check_assets.py
python scripts/run.py
```

已有仓库可另建工作目录，保持当前平台分支与未提交文件不动：

```powershell
git fetch origin --tags
git worktree add --detach ../PLIAC-graph-check 02aacf1b8a442f168e146f83e0e72cb27f0033bb
```

标签检出默认是 detached HEAD，适合验证；要在图谱上继续开发可 `git switch -c graph-validation`。源码版本包含内置课程种子和测试，不包含 `.gitignore` 排除的模型密钥、本地上传资料、`outputs` 建图结果和真实学习记录。需要复核某一本资料的实际建图结果时，应另提供经允许分享的输入和图谱导出，不能靠 Git 历史恢复未入库数据。

| 部分 | 实现 | 作用 |
| --- | --- | --- |
| 平台装配 | `src/pliac/main.py` | 统一挂载课程、图谱、资料与学习接口 |
| 学习工作流 | `src/pliac/workspace.py` | 起点资料、小节选择、提示、作答、段落困惑、报告与手册 |
| 平台接口 | `src/pliac/api.py` | `/api/learning`、学习事务及教师章节规则 |
| 知识子模块 | `src/learning_agent/` | 保留已有建图、资源推荐、证据、诊断、复习和发布机制 |
| 学习 / 复核页面 | `/learn`、`/review` | 共享 `course_id` 与稳定匿名学习编号 |
| 兼容入口 | `learning_agent.main:app` | 指向平台应用，已有启动与测试可继续运行 |

本地目录沿用 `learning-agent`，仓库远端是 PLIAC；平台化通过包边界实现，不搬动 `outputs/course_graph` 或 `outputs/documents`。启动器检查 `learning_workspace` 能力，避免复用只有旧图谱接口的服务。

## v7 对齐与当前边界

| 文档要求 | 本轮行为 | 尚未替代的部分 |
| --- | --- | --- |
| §2.2 起点画像 | 目标、背景、兴趣与节点三档自评；自评单独形成证据 | 尚无自动对话初诊；任务仍须人工复核 |
| §2.2、§4.3 学习小节 | 根据先修前沿、到期和补学状态选点，组合已发布概念、目标与审核资源；留存理由与规则版本 | 不是大模型现场生成的个性化教案；不同学习者共享课程事实 |
| §2.2 段落困惑 | 必须引用当前小节中的逐字原文；保存问题与节点、段落及证据引用 | 暂无模型逐段解读 |
| §4.4 受控提示 | 只释放已请求的提示层级，服务端累计记录；学生接口不返回参考答案与判据 | 正式任务的题目与提示由教师审核的课程节点提供 |
| §3.3 原始证据分离 | 原始自评、作答与困惑留在 evidence；诊断留在 diagnoses；小节与提示留在 workspace | 不自动生成教师姓名、审核结论或掌握标签 |
| §2.4 章节报告 | 教师配置必达节点，保存草稿并发布；逐节点检查当前状态，附依据与证据引用 | 没有规则时显示待配置；没有独立的新章节题库或自动评分 |
| §2.3 知识手册 | 汇总待核验、补学、困惑、提示依赖与多次提交，支持文本导出 | 多次提交仅提示复核，不自动解释为能力不足；尚无实训错误库执行结果 |
| §2.5 续学与复习 | 恢复最近小节、作答草稿、提示、提交；沿用图谱到期规则，保留历史报告 | 不包括 Docker 环境恢复、语音视频或完整大模型聊天记忆 |
| §5.5 一致性 | 同一学习者 revision 原子提交，会话和证据共用 HEAD；旧记录按需兼容 | 本地界面不是多用户部署权限边界 |

## 数据契约

新 `workspace.json` 与 `profile.json`、`evidence.json`、`diagnoses.json`、`actions.json`、`resource_uses.json` 一起写入 `learners/<编号-摘要>/revisions/<版本>/`。只有完整 revision 写完才替换 `HEAD.json`。旧 revision 没有 workspace 文件时使用空视图，读取不改写历史数据；原有图谱保存资料、复核等操作会保留 workspace。

学习写请求必须携带 `student_id`、`course_version`、`expected_version` 和 `request_id`。版本冲突返回 409，前端保留未提交文字，刷新后重试；同一请求 ID 的相同重试不重复添加证据，换成其他内容会拒绝。服务端校验学生归属、当前小节和课程版本，不信任客户端提交的提示等级。

每个小节绑定课程 / 章节 / 节点 / 任务版本，保留材料快照、选点理由、资源筛选过程和已给提示。课程新版本发布后，旧小节继续可读但不能继续写入，需建立新小节。同一节点的同一道题即使换了版本号，已给提示也不清零；独立复测需要教师准备没有看过提示的新题。

教师页「节点诊断任务」支持补题和换题，任务 ID 保持稳定，内容改变时递增任务版本；保存调用现有草稿审核失效机制。必须填写问题、参考答案、至少一条判据和四级提示，再经节点人工审核及课程发布后才能用于正式学习。学生接口仍不暴露未请求的提示、参考答案或评分判据。

章节规则放在 `chapters[].completion_policy`：

```json
{
  "mode": "all_required_mastered",
  "required_node_ids": ["节点ID"],
  "configured_by": "实际制定人",
  "basis": "具体课程要求"
}
```

必达节点必须非空、无重复且属于本章。规则配置不直接改已发布课程。报告读取现有派生状态，因此待复核作答、冲突、内容变更与到期复习均会阻止相应必达节点通过。已保存报告是注明时间和版本的历史快照；页面实时报告反映当前状态，两者不混用。

## ChatEval 参考

检查了 `apps/dialog_demo/app/session_store.py` 的稳定会话编号、轮次和磁盘恢复，`task_service.py` 的任务上下文，以及 `recording_store.py` 的按样本保存媒体设计。未在根目录发现可据此确认移植授权的 LICENSE，因此本轮只借鉴职责拆分，使用 PLIAC 现有事务存储重新实现；未复制其业务代码、原实验题目、学生数据或 B/D/I 公式。摄像头实现仍是后续任务。

## 验证与后续

`tests/test_learning_workspace.py` 使用临时目录验证兼容恢复、服务端提示计数、防止伪独立作答、跨学生隔离、课程升级、请求幂等、并发版本、事务中断、引用校验、达标规则与间隔复习。`tests/test_ui_learning.py` 通过真实 Chromium 操作学习端和教师端，检查保存 / 恢复、拒绝提示后掌握、实际人工复核入口、发布规则、报告导出、深色及手机布局。测试中的教师、课程和学习者全部为合成数据。

浏览器结果与截图保存在 `outputs/verification/learning-workspace-report.json`、`learning-workspace-desktop.png`、`learning-review-desktop.png`、`learning-workspace-mobile-dark.png`。测试不使用正式课程和学习记录。

0.7.0 已加入 [机器学习 Lab](ml-lab.md)：情境模板与任务判据分离，执行真实 scikit-learn 参数实验，完成数据检查、划分、比较、方案封存与测试，并保存提示、证据和新数据复测记录。它使用有界参数引擎，学生自由 Python 代码的 Docker 隔离执行仍需另行建设。后续工作包括初始实测与个性化教学编排、模型情境生成与语义复核、受控讲解、摄像头授权与回看、部署权限和真实学习者试跑。
