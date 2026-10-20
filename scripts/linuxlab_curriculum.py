"""Authored LinuxLab alignment; does not modify the extraction pipeline."""

CONTRACT_HASH = "af9086405f85d7bbc01ec5f5d75edbbd172480297d7c748841e120dea67b56b4"
CONCEPT_MAP = {
    "paths": ["cwd", "absolute", "relative", "cd"], "hidden": ["ls"],
    "mkdir": ["mkdir"], "copy": ["cp"], "move": ["mv", "rm"],
    "glob": ["glob"], "archive_read": ["tar", "relative"],
    "logs": ["cat", "tail", "log_record"], "config": ["config_record"],
    "editing": ["vim"], "permissions": ["identity", "file_permissions", "chmod"],
    "execution": ["script"], "process": ["process", "ps", "top"],
    "archive_build": ["tar"], "integrity": ["file_integrity"],
}
ROWS = [
    ("locate", "定位与准备", ["paths", "hidden", "mkdir"], "确认当前位置与隐藏目录项，准备任务目录。"),
    ("backup", "保全原始资料", ["copy", "hidden", "integrity"], "建立完整副本，保留原件、隐藏项与目录层级。"),
    ("organize", "整理与精确清理", ["move", "glob", "integrity"], "移动指定材料，只清理符合规则的普通文件。"),
    ("extract", "查看与恢复归档", ["archive_read", "paths"], "先观察归档成员，再恢复正确的目录结构。"),
    ("interpret-log", "辨认有效日志", ["logs"], "按记录类型和时间确定有效业务信息。"),
    ("configure", "编辑实际配置", ["config", "editing", "logs"], "用 Vim 将核实的信息写入配置并保存。"),
    ("permissions", "最小授权与执行", ["permissions", "execution", "config"], "设置权限并亲自执行脚本，观察实际结果。"),
    ("process", "观察活跃进程", ["process"], "启动短时练习程序，确认本次仍存活的进程身份。"),
    ("deliver", "核验最终交付", ["archive_build", "config", "permissions", "copy", "integrity"], "核对归档内的内容、路径、类型与权限，保留原始备份。"),
]


def activity():
    return dict(id="linuxlab", title="LinuxLab · 九关实训", engine="linuxlab", href="/linux-lab",
                bridge_schema=1, contract_version=1, contract_hash=CONTRACT_HASH,
                lab_course_id="linux-foundations", concept_map=CONCEPT_MAP,
                stages=[dict(phase=i, task_id=key, title=title, concepts=concepts, goal=goal,
                             node_ids=list(dict.fromkeys(n for c in concepts for n in CONCEPT_MAP[c])))
                        for i, (key, title, concepts, goal) in enumerate(ROWS, 1)],
                validation_scope="真实文件与当前进程的检查；不证明独立完成或概念掌握。")


NODES = [
    ("tail", "search", "tail 末尾观察", "core:tail-invocation",
     "tail 默认输出文件末尾若干行；-n 指定行数，-f 持续观察追加内容。看到末尾只代表缩小观察范围，不代表最后一行就是所需业务记录。",
     "在无关练习文件 events.log 上使用 `tail -n 5 events.log`；观察持续追加时可用 -f，Ctrl-C 停止观察。",
     "把最后一行或 tail -f 当作业务筛选规则。", "末尾十行仍没有目标记录，能否断言它不存在？",
     "不能；tail -n 10 只展示末尾窗口，需扩大范围或根据记录类型筛选。"),
    ("log_record", "search", "日志记录语义", "lab:tasks.py",
     "日志行包含时间、记录类型和业务字段。应先确定所需类型，再在该类型内找最新有效记录；多个字段须来自同一条记录。LinuxLab 的后续心跳不替换最近的有效业务记录，这是本实验的数据约定。",
     "例：10:00 READY PORT=42；10:01 HEARTBEAT。心跳更新并不改变最近 READY 的 PORT。应先解释类型，再提取字段。",
     "混用不同行的字段，或把最新心跳当作最新业务指令。", "为什么最新一行不一定是最新有效业务记录？",
     "最新描述时间，有效还受记录类型及业务条件限制；必须同时满足，不能拼接不同行的字段。"),
    ("config_record", "scripts", "键值配置结构", "lab:tasks.py",
     "配置文件按应用约定组织字段。LinuxLab 使用规定的 KEY=value 格式，必需字段各出现一次且不接受额外字段；修改后要保存到磁盘。这是实验应用的数据格式，并非所有 Linux 配置都遵守同一语法，也不应把未知配置当 Shell 脚本执行。",
     "无关练习 example.conf 中保留 NAME=demo，将 PORT=42 改为 PORT=43；保存后重新读文件，检查重复键和遗漏键。",
     "认为在编辑器里看到改动就等于磁盘已保存，或所有配置都可用 source 执行。", "为什么两行 PORT=42、PORT=43 不能简单当作已正确更新？",
     "键重复；解释规则由应用决定，本实验明确拒绝重复。应按规定只保留一次目标值并保存核对。"),
    ("vim", "search", "Vim 模式与保存", "vim:usr_02.txt",
     "Vim 普通模式解释编辑命令，插入模式写入文本，命令行模式执行保存等操作。普通模式按 i 进入插入，Esc 返回；:w 保存，:wq 保存并退出，:q! 放弃未保存修改并退出。缓冲区变化与磁盘文件变化需要区分。",
     "在无关 scratch.txt 中练习：i 输入一行，Esc 后 :w 保存；重新打开确认。可用 :help 或 vimtutor 自主练习。",
     "在普通模式直接输入配置文本，或把 :q! 当作保存退出。", "改动后用 :q! 退出，磁盘会保留刚才的改动吗？",
     "未保存的改动会被放弃；需要先 :w 或用 :wq 保存并退出。"),
    ("top", "processes", "top 动态进程观察", "man:top",
     "top 动态显示系统进程及资源信息。PID 对应当前运行实例，应结合命令名、所有者和启动语境确认身份，不能只猜最大 CPU 行。进程结束后 PID 可能被复用，旧记录不能证明目标仍在运行。",
     "用 `top` 观察本机进程列表，按 q 退出；与 `ps -p PID -o pid,comm,args` 的快照比较。练习只观察自己明确启动的进程。",
     "把日志序号当作 PID，或认为上一个脚本退出后仍常驻。", "保存了一个 PID，过一段时间为什么还需要核实身份？",
     "原进程可能退出且 PID 可能复用；需重新检查当前实例的命令、身份和任务语境。"),
    ("file_integrity", "files", "文件副本完整性", "core:cp-invocation",
     "完整副本要求明确比较范围：内容、目录层级、隐藏项、文件类型及任务要求的元数据。文件名相同不代表内容相同；复制成功也不能单独证明源文件未被改变。需要在操作前后核对，并保留原始资料。",
     "对无关目录 source-notes 建立副本，分别列出含隐藏项的目录树，比较文本内容与类型。先确认目标层级，避免多出一层同名目录。",
     "只看可见文件名，遗漏隐藏项或意外移动了原件。", "备份中看到了所有可见文件名，是否足以证明完整？",
     "不足；还需检查隐藏项、子目录、内容、类型及要求的元数据，并确认原件仍完整。"),
]
PREREQUISITES = [
    ("relative", "tail", "读取末尾前必须能准确指定输入文件。"),
    ("cat", "log_record", "本课先读完整文本，再解释行的业务类型与字段。"),
    ("relative", "vim", "编辑前需确定正在修改的目标路径。"),
    ("process", "top", "动态观察需先理解运行实例和 PID。"),
    ("cp", "file_integrity", "副本核验需明确复制对象、目标层级与源文件保留语义。"),
]
RELATED = [
    ("tail", "log_record", "末尾观察提供日志窗口，业务语义仍需单独判断。"),
    ("vim", "config_record", "编辑器负责修改和保存文本，配置约束由应用规定。"),
    ("file_integrity", "tar", "归档交付也要核验内部成员与内容。"),
    ("top", "ps", "动态视图和快照均可提供进程观察证据。"),
]
