# 完整示范课程验收

## 直接开始

双击根目录的「启动学习平台.cmd」，在课程页打开 **机器学习分类入门：从数据到可靠评估**。不需要导入教材、配置模型或先编写题目。若启动日志端口为 8010，直接访问：

`http://127.0.0.1:8010/learn?course_id=ml_acceptance_demo`

页面预填新的匿名验收编号。点击「进入 / 恢复」，保存学习目标，再点击「安排下一小节」。同一课程、同一编号可续学；想从头验收时换一个编号即可。编号与原课程记录分开。

## 已完成的课程内容

两章、10 小节，预计 45—60 分钟。每节含学习目标、概念讲解、教学算例、常见误区、四级提示、诊断题与备用复测题，共 20 道四选一题。算例采用教学数据。每节提供相应官方资料链接。

| 章节 | 学习小节 | 完成规则 |
| --- | --- | --- |
| 准备可信的数据 | 样本/特征/标签、集合划分、训练/验证/测试职责、准确率、预处理泄漏 | 本章 5 个节点均有当前有效的独立核验结果 |
| 选择能泛化的模型 | 复杂度、欠拟合、过拟合、按预设规则选模型、最终评估与复现 | 本章 5 个节点均有当前有效的独立核验结果 |

## 建议验收路径

1. **独立通过**：阅读讲解，在未请求提示时选答案并提交。正确时节点变绿，下一小节沿先修路线前进。页面显示题目判定、解析及作答来源。
2. **答错后补学**：故意选错一题。节点变红，知识手册收录本节点。点击「安排补学 / 复测」，仍停留在该知识点，提供另一道题；独立答对后可以继续。
3. **提示依赖**：在另一节点请求一级提示后答对。状态仍是待核验，换题独立通过才变绿；手册仍保留提示记录。每个节点配有两道固定题，题目提示和解析的查看记录会保留。需要进一步核验时由教师另出题，并通过真实作答和人工复核记录结论。
4. **续学**：选择选项、填写可选思路，等待保存提示或手动保存，刷新后用同一编号进入。当前小节、选项、思路、提示及已提交答案均应恢复。
5. **完成课程**：依次通过 10 个节点，进度显示 `10 / 10`，两章显示「当前达标」。分别保存报告，导出完整学习记录和个人知识手册。历史报告保留当时结论；到期复习会改变实时状态，不改写旧报告。
6. **困惑与人工复核**：点击段落旁「不明白」，填写具体问题。困惑交由教师复核。教师页可核对题目、原始证据和规则判断，并填写真实复核依据；内置课程的题库和章节规则只读。
7. **显示**：右上角月亮/太阳切换主题；在手机宽度检查选项、提示、报告和导出入口。

## 判定和数据

固定题库位于 `data/acceptance_course.json`，构建与判题逻辑位于 `src/learning_agent/acceptance_course.py`。学生作答仍保存为独立原始证据；系统规则判断另存为 diagnosis，标记 `assessment_origin=objective_rule`、`review_status=rule_verified`、`rule_id=demo-choice-v1`。

服务端根据题库核对选项，不接收客户端宣称的分数、通过状态或提示等级。解析展示后，该题记录为已获得辅助信息；历史作答的原始提示等级不改写。两套题共享知识点，但分别保留任务 ID 和接触记录。

内置示范课使用独立存储：`outputs/course_graph/acceptance_demo/v1/learners/`。正式课程的审核、发布及人工诊断流程保持原有规则。

## 复现验证

```powershell
python -X utf8 -m unittest discover -s tests -p test_acceptance_course.py
python -X utf8 tests/test_ui_acceptance_course.py
```

测试使用临时目录中的合成学习者，不改动实际课程或学习记录。浏览器报告在 `outputs/verification/acceptance-course-ui-report.json`；截图为 `acceptance-course-desktop.png`、`acceptance-course-mobile-dark.png` 与 `acceptance-course-complete.png`。

内容参考：[数据划分与模型选择](https://scikit-learn.org/stable/modules/cross_validation.html)、[预处理和泄漏](https://scikit-learn.org/stable/common_pitfalls.html)、[验证曲线](https://scikit-learn.org/stable/modules/learning_curve.html)、[准确率](https://scikit-learn.org/stable/modules/model_evaluation.html#accuracy-score)。练习、讲解组织与数值案例为本项目编写。
