# 扫描图谱压力测试样本

这两份 JSON 是用户本地扫描结果的原样快照，保留概念、关系、页码证据、章节层级和成员关系。不是随机生成数据，也不是人工审核后的课程图谱。

| 文件 | 扫描资料 | 概念 | 关系 |
| --- | --- | ---: | ---: |
| computer-organization.json | 计算机组成与设计：硬件／软件接口（第二版） | 500 | 2,000 |

当前扫描程序限制展示 500 个概念、2,000 条关系；这是截取后的真实大图，而非扫描出的全部候选。`manifest.json` 保存文件字节数、SHA-256、层级规模和扫描统计（包括丢弃数量）。层级视图投影后的可见节点、边数量会不同。

## 运行

在仓库根目录安装 `requirements.txt` 与 `requirements-dev.txt` 中的依赖，并运行 `python -m playwright install chromium`。先启动服务：

```powershell
python scripts/run.py --no-browser
```

使用启动日志中实际输出的端口（下面以 8010 为例）：

```powershell
python scripts/benchmark_scanned_graph.py --sample computer-organization --base-url http://127.0.0.1:8010
```

仅检查文件完整性和边端点，无需启动服务：

```powershell
python scripts/benchmark_scanned_graph.py --verify-only
```

报告位于 `outputs/verification/large-graph-<sample>.json`，记录首屏、悬停、拖动、缩放、标签切换、空闲阶段的 CPU 时间、帧间隔、长任务、渲染器信息和脚本哈希。比较结果时固定样本、代码提交、浏览器、机器与渲染后端；软件渲染和硬件 GPU 的数值不可直接混用。

回放会拦截文档查询并提供样本，不导入或修改本机课程、文档和学习记录。JSON 里的本地 `source_url` 是扫描时保留的溯源字段；本仓库不包含原始 PDF，因此原书预览不属于回放验收范围。样本中的原文证据来自所列资料，不应当作项目原创教材或人工审核结论。

这是**文档图谱**数据格式，应在 `/documents` 渲染路径回放；不要导入有 2 MB 限制的**课程图谱**编辑器。
