# Linux 命令入门课程

课程模板位于 `data/course_templates/linux_command_line/course.json`，稳定编号为
`811cf1ea02b554fa9987cce724b5f02a`。课程使用现有 CourseGraphStore、课程管理、
图谱编辑器、LearnMargin 范围选择和教学材料通路。配套 [LinuxLab 接入](linuxlab-integration.md) 使用本机真实终端。

46 个知识点分为 8 个单元：认识命令行、目录与路径、文件操作与归档、查看与查找、
数据流与管道、用户与权限、进程与作业、Shell 自动化。图谱包含 42 条先修关系、
8 条易混淆关系、19 条相关关系。章节只是导航分组，不作为知识节点或先修链。

每个知识点包含中文解释、操作例子、常见误解、自检题、参考答案、评分依据、
四级提示及文档定位。运行环境按 Linux、Bash、GNU 工具编写；脚本练习、
网页不执行学习者提交的 Shell；配套实训在明确启动的本机 LinuxLab 终端中操作。

## 装填与查看

在仓库根目录执行：

```powershell
python -X utf8 scripts/install_course_draft.py data/course_templates/linux_command_line/course.json
```

安装后进入“课程管理”，选择“Linux 命令入门：从路径到 Shell 自动化”的
“编辑图谱”。默认本地服务的直接入口为：

<http://127.0.0.1:8010/author?course_id=811cf1ea02b554fa9987cce724b5f02a>

知识点详情可查看定义、目标、先修、易混淆点、诊断问题及来源；“讲义与知识图谱”
入口可沿用平台现有模型配置，从已链接的自编教学材料生成整课、章节或单点讲义。
模板自带的课程图谱无需调用模型即可查看；本次装填不代表已运行模型生成讲义。

安装使用独立的 `outputs/course_graph/courses/<课程编号>/draft.json`。
重复安装完全相同模板是无操作；如果现有草稿已经修改，安装器拒绝覆盖，
须通过已有编辑流程合并。已有发布记录、其他课程和学习者数据不做迁移或修改。

## 证据与审核

本课程的中文讲解与题目由智能体自编；GNU Bash、Coreutils、Grep、Findutils、Tar、
Linux man-pages / procps 文档和 Software Carpentry 是技术核验入口。
未复制整本教材或把社区答案冒充教师教案。文档链接、章节定位保存在 `sources`，
节点的 `evidence_refs` 指向参考文档及本地讲解段落，关系的 `evidence_refs`
指向两端概念段落。技术出处不等于作者原文明确宣称这条教学先修关系。

先修边的 `basis_kind=authored_teaching_dependency`，理由针对本课任务；
相关和易混淆关系不限制学习顺序。`term-audit.json` 记录概念原子性、领域资格、
准入和拒绝项，策略版本为 `authored-linux-command-v1`。这是自编课程的候选审计，
不是对通用图谱生成器的修复，也不是人工学科审核。

全部节点、关系和资源保持 `review_status=draft`。安装后可查看、编辑和生成讲义；
按项目 v7 规范，教师审核后才能正式发布到学习端。安装器不填写审核人、不建立
掌握诊断、不写入模拟学习者，也不使用 ML 验收课程的 `demo-choice-v1` 评分规则。

## 维护

`scripts/build_linux_course.py` 是该课程的显式编写源，不调用模型或推断关系。
修改它后运行以下命令可重新构建仓库模板，不会同步覆盖已安装课程：

```powershell
python -X utf8 scripts/build_linux_course.py
python -X utf8 -m unittest discover -s tests -p "test_linux_course.py"
python -X utf8 tests/test_ui_linux_course.py
python -X utf8 scripts/verify_linux_examples.py --wsl Ubuntu
```

课程内容、关系和题目仍需学科核验；结构测试、浏览器验收及本地 Bash 算例
只能验证相应契约，不能作为真实教学效果或学习者掌握证据。
