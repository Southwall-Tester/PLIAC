"""Author the Linux curriculum seed. This is authored content, not an extractor.

Run with Python UTF-8. Runtime installation is a separate, non-overwriting step.
No human review or learner records are created by this script.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from learning_agent.course_graph import validate_graph
import linuxlab_curriculum as lab_curriculum

DEST = ROOT / "data/course_templates/linux_command_line"
COURSE_ID = "811cf1ea02b554fa9987cce724b5f02a"
POLICY = "authored-linux-command-v1"

CHAPTERS = [
    ("shell", "01 认识命令行", "理解 Shell、参数、帮助与引号。"),
    ("paths", "02 目录与路径", "判断当前位置，准确定位文件。"),
    ("files", "03 文件操作与归档", "在练习目录中创建、复制、移动、删除和打包文件。"),
    ("search", "04 查看与查找", "区分文件名匹配、内容搜索与正则表达式。"),
    ("streams", "05 数据流与管道", "追踪输入输出，组合命令完成文本统计。"),
    ("permissions", "06 用户与权限", "区分文件、目录权限并作最小必要授权。"),
    ("processes", "07 进程与作业", "识别进程、发送信号、理解前后台作业。"),
    ("scripts", "08 Shell 自动化", "用变量、退出状态、循环和脚本组织重复工作。"),
]

# id, chapter, title, primary documentation, explanation, worked example,
# misconception, question, answer. All Chinese teaching text and tasks are authored.
NODES = [
    ("shell", "shell", "Shell 命令解释器", "bash:What-is-a-shell_003f",
     "终端提供文字交互界面，Shell 负责读取命令、展开参数并调用程序。Bash 是一种 Shell；Linux 是操作系统内核，三者不是同一个对象。命令既可能是 Shell 内建，也可能是外部程序。",
     "在 Bash 中输入 `type cd` 与 `type ls`，比较内建命令和外部程序的查询结果。若环境定义了别名，结果可能先显示别名。",
     "把终端窗口、Bash 和 Linux 当作同一概念。", "关闭终端窗口和执行一条 ls 命令分别涉及什么角色？",
     "终端负责交互界面；Bash 读取并解释 ls，通常启动外部 ls 程序。关闭窗口不等于卸载 Bash 或关闭整个 Linux 系统。"),
    ("syntax", "shell", "命令参数", "bash:Simple-Commands",
     "简单命令通常由命令名和若干参数构成。选项改变行为，操作数指明处理对象。Shell 完成分词和展开后，把参数交给命令；不同命令的选项含义需要分别查证。",
     "`ls -l notes` 中，ls 是命令名，-l 是选项，notes 是操作数。GNU 命令常用 `--` 结束选项，如 `ls -- -report`。",
     "认为所有命令的 -r 都表示递归。", "在 ls -l notes 中，哪一项是路径，哪一项控制显示方式？",
     "notes 是路径操作数，-l 控制长格式显示。-l 不是文件名，ls 不会因此改变 notes 的内容。"),
    ("help", "shell", "命令帮助检索", "bash:Bash-Builtins",
     "遇到不熟悉的选项，应先查本机帮助。Bash 内建命令可用 help；外部程序常提供 --help，系统手册可用 man。帮助内容与当前安装版本相关，不能把某个命令的选项照搬给另一个。",
     "`help cd` 查询 Bash 的 cd；`ls --help` 查询 GNU ls；安装了手册时用 `man ls`，按 q 退出。",
     "man cd 没有结果就认为 cd 不存在。", "如何确认当前 Bash 的 cd 支持哪些选项？",
     "使用 help cd，必要时用 type cd 确认它是否为内建或被函数覆盖。不能仅凭是否存在独立 man 页面判断。"),
    ("quoting", "shell", "Shell 引号", "bash:Quoting",
     "引号控制 Shell 对字符的解释。单引号基本保留字面内容；双引号保留参数展开等少数处理，同时保护空格。包含空格的路径通常应作为一个带引号的参数传递。",
     "`ls 'my notes'` 传入一个路径参数；`ls my notes` 传入两个。变量用 `printf '%s\\n' \"$HOME\"` 可在展开后保留为一个参数。",
     "认为引号只是装饰，或单双引号的变量展开完全相同。", "文件夹名为 my notes，应传几个参数给 ls？请写出命令。",
     "传入一个路径参数：ls 'my notes' 或 ls \"my notes\"。不加引号会被分为 my 与 notes 两个参数。"),
    ("cwd", "paths", "当前工作目录", "core:pwd-invocation",
     "每个进程都有当前工作目录，相对路径从它开始解析。pwd 显示当前位置。执行 ls 只列出内容，不改变工作目录；不要根据终端上最后看到的目录名猜测当前位置。",
     "先执行 `pwd`，再执行 `ls /tmp`，然后再次 `pwd`。两次位置应相同，除非中间另有改变目录的操作。",
     "列出某目录就等于进入该目录。", "当前位于 /home/lin，执行 ls /tmp 后相对路径 notes 从哪里开始？",
     "仍从 /home/lin 开始，指向 /home/lin/notes。ls /tmp 没有改变工作目录。"),
    ("absolute", "paths", "绝对路径", "carp:02-filedir",
     "在本课程的 Linux 文件系统中，以 / 开头的路径从根目录解析。绝对路径不依赖当前工作目录，但它指向的对象可能不存在，也可能因权限不足无法访问。",
     "`/home/lin/notes` 从根目录定位；无论当前在 /tmp 还是 /home/lin，路径的起点都相同。",
     "以为绝对路径保证文件存在。", "在 /tmp 中访问 /home/lin/notes，是相对路径还是绝对路径？",
     "是绝对路径，因为以 / 开头；对象是否存在、是否可访问还要另行检查。"),
    ("relative", "paths", "相对路径", "carp:02-filedir",
     "相对路径不以 / 开头，从当前工作目录解析。. 表示当前目录，.. 表示父目录。判断路径时应先确定当前位置，再逐段解析，而不是记住固定字符串。",
     "当前目录为 /home/lin/project，`../data` 指向 /home/lin/data；`./data` 指向 /home/lin/project/data。本例假定路径中没有符号链接。",
     "把 ../data 和 ./data 当作同一个位置。", "从 /home/lin/project 出发，../../tmp 对应哪个绝对路径？假定没有符号链接。",
     "先到 /home/lin，再到 /home，再进入 tmp，因此是 /home/tmp，而不是 /tmp。"),
    ("cd", "paths", "cd 切换目录", "bash:Bourne-Shell-Builtins",
     "cd 改变当前 Shell 的工作目录，后续相对路径随之改变。目标必须是可进入的目录。未给参数时通常进入 HOME；cd .. 进入父目录。子进程的 cd 不会修改父 Shell 的位置。",
     "`cd /tmp` 后用 `pwd` 核对。脚本内部执行 cd，只影响脚本进程及其子进程，不会把调用它的交互 Shell 带过去。",
     "以为单独运行脚本中的 cd 能永久改变调用者目录。", "为什么 bash change-dir.sh 内的 cd /tmp 不会改变外层 Shell 的目录？",
     "脚本运行在另一个 Bash 进程中，改变的是该进程的工作目录；父 Shell 的工作目录不受影响。"),
    ("ls", "paths", "ls 列出目录项", "core:ls-invocation",
     "ls 查看文件名或目录内容。-l 使用长格式，-a 包括点开头的隐藏名称，-d 显示目录自身。ls 的输出格式面向阅读，脚本处理任意文件名时不应靠拆分 ls 输出。",
     "比较 `ls -l .` 与 `ls -ld .`：前者列出目录内容，后者显示当前目录自身。",
     "ls 看不到文件就断定目录为空。", "检查当前目录自身的权限应使用 ls -l . 还是 ls -ld .？",
     "使用 ls -ld .。-d 阻止展开为目录内容，-l 显示该目录项的长格式信息。"),
    ("mkdir", "files", "mkdir 创建目录", "core:mkdir-invocation",
     "mkdir 创建目录；默认要求父目录已经存在。-p 可以补建缺少的父目录，已有目录通常不会导致失败。创建目录不等于改变当前位置。",
     "在专用练习目录中运行 `mkdir -p project/data`，随后用 `ls -ld project/data` 核对。",
     "认为 mkdir 会自动进入新目录。", "父目录 project 尚不存在，如何一次创建 project/data？",
     "使用 mkdir -p project/data。创建后当前工作目录不变，如需进入还应执行 cd。"),
    ("cp", "files", "cp 复制文件", "core:cp-invocation",
     "cp 把源内容复制到目标，源文件通常保留。目标是已有目录时，文件复制到该目录内；目标是文件路径时，可能覆盖它。复制目录通常需要递归选项。",
     "在练习目录已有 notes.txt 和 backup/ 时，`cp -i notes.txt backup/` 创建或替换 backup/notes.txt；-i 在覆盖前询问。",
     "把复制当成移动，或者忽略目标已存在时的覆盖。", "cp notes.txt backup/ 成功后，原 notes.txt 是否还在？",
     "通常仍在；复制在 backup 中生成副本，并未删除源文件。目标原有同名文件可能被覆盖。"),
    ("mv", "files", "mv 移动与重命名", "core:mv-invocation",
     "mv 用于移动或重命名目录项。目标为已有目录时放入该目录；目标为新路径时改用该名称。成功移动后原路径通常不再指向原对象，已有目标还可能被覆盖。",
     "在练习目录执行 `mv -i draft.txt final.txt`，观察原名称与新名称。跨文件系统的移动实现可能涉及复制后删除。",
     "把 mv 当成会保留原件的 cp。", "将 draft.txt 改名为 final.txt 后，应在哪个路径找它？",
     "成功重命名后在 final.txt 找到它，draft.txt 原名称消失；这不是额外生成一份副本。"),
    ("rm", "files", "rm 删除目录项", "core:rm-invocation",
     "rm 删除指定文件名，通常不经过桌面回收站。删除目录需要递归等选项；本课只在专用练习目录删除明确命名的样本。先核对路径，再删除；不要把未知通配符直接交给 rm。",
     "先用 `ls -- ./scratch.txt` 确认样本，再执行 `rm -i -- ./scratch.txt`。这是真实删除，仅对可丢弃样本操作。",
     "以为 rm 一定可从回收站恢复。", "删除练习目录内 scratch.txt 前，应核对哪些信息？",
     "核对 pwd、明确的相对或绝对路径及文件内容确为可丢弃样本；rm -i 只增加确认，不提供回收站恢复保证。"),
    ("symlink", "files", "符号链接", "core:ln-invocation",
     "符号链接保存指向目标的路径。访问链接通常会继续解析目标；目标被移走后可能形成悬空链接。相对链接目标按链接所在目录解析，而不是按访问者的当前目录解析。",
     "在练习目录中用 `ln -s notes.txt latest` 建立链接。删除 latest 这个链接名不会直接删除 notes.txt。",
     "把链接当成独立内容副本。", "把 notes.txt 移到别处后，指向它的符号链接一定还能读取内容吗？",
     "不一定；原目标路径不存在时链接会悬空。符号链接保存的是路径，不是文件内容副本。"),
    ("tar", "files", "tar 归档", "tar:Basic-tar",
     "归档把多个文件及相关元数据组织进一个包，压缩是另一项操作。GNU tar 的 -c 创建归档，-t 列出归档内容，-x 解包，-f 指定归档文件。解包前应先检查内容。",
     "在练习目录用 `tar -cf notes.tar notes` 打包 notes/；用 `tar -tf notes.tar` 查看内容。此处未开启 gzip 压缩。",
     "把所有 .tar 文件都当成压缩文件。", "tar -cf notes.tar notes 一定会压缩内容吗？如何先查看包里有哪些文件？",
     "不一定，此命令只归档；用 tar -tf notes.tar 查看成员，再决定是否在隔离目录解包。"),
    ("cat", "search", "cat 输出文件内容", "core:cat-invocation",
     "cat 顺序读取文件并写到标准输出，可用于查看较短文本或连接多个文件。它本身不编辑源文件。大文件或二进制文件不适合直接全部输出到终端。",
     "`cat first.txt second.txt` 按参数顺序输出两份内容，默认不会自动在文件之间添加分隔标题。",
     "以为 cat 会自动修改或合并源文件。", "cat first.txt second.txt 是否会把第二个文件写进第一个文件？",
     "不会；它把两份内容顺序写到标准输出，源文件不因此改变。保存到新文件需要另行重定向。"),
    ("grep", "search", "grep 文本筛选", "grep:Matching-Control",
     "grep 筛选与模式匹配的文本行。-F 按固定字符串匹配，-n 显示行号，-i 忽略大小写。搜索内容与搜索文件名是两种任务；本课先用 -F 避免把标点误作正则。",
     "`grep -nF 'ERROR' app.log` 显示包含 ERROR 的行及行号。它不是查找文件名中含 ERROR 的文件。",
     "把 grep 的模式当成 Shell 文件名通配符。", "查找 app.log 中包含字面字符串 a.b 的行，怎样避免点号表示任意字符？",
     "使用 grep -F 'a.b' app.log；-F 把模式作为固定字符串，点号保持字面含义。"),
    ("find", "search", "find 文件查找", "find:Name",
     "find 从给定起点遍历文件树，再按名称、类型等条件筛选。-name 的模式应加引号，交由 find 对每个名称匹配。只查文件可结合 -type f。",
     "`find . -type f -name '*.log'` 从当前目录向下查找普通日志文件。引号防止当前 Shell 提前展开 *.log。",
     "以为 find 在文件内容中搜索单词。", "为什么 find . -name '*.txt' 中的星号通常要加引号？",
     "让模式原样传给 find，而不是先由 Shell 展开为当前目录中若干文件名；find 才能在遍历时对每个名称匹配。"),
    ("glob", "search", "文件名通配展开", "bash:Filename-Expansion",
     "Bash 可把未引用的文件名模式展开为匹配路径。* 匹配任意长度，? 匹配单个字符。默认设置下点开头名称通常不被 * 匹配；无匹配时的行为还受 Shell 选项影响。",
     "存在 a.log、b.log 时，`printf '%s\\n' *.log` 通常收到两个路径参数；`printf '%s\\n' '*.log'` 输出字面模式。",
     "把文件名通配符等同于 grep 正则。", "文件 a.log 与 b.log 存在时，带引号的 '*.log' 会被 Bash 展开吗？",
     "不会。单引号保留字面字符串 *.log；未引用的模式才按当前 Shell 的文件名展开规则处理。"),
    ("regex", "search", "正则表达式", "grep:Regular-Expressions",
     "正则表达式描述文本模式。使用 grep -E 时，^ 表示行首，$ 表示行尾，. 表示任意单个字符，* 重复前一个元素。它与 Shell 文件名模式采用不同语法和匹配对象。",
     "`grep -E '^ERROR' app.log` 匹配以 ERROR 开头的行；`grep -F 'ERROR' app.log` 在行内任意位置查固定字符串。",
     "以为正则中的 *.log 与文件名模式 *.log 含义一样。", "只保留以 WARN 开头的文本行，应使用什么 grep 模式？",
     "使用 grep -E '^WARN' app.log。^ 约束行首；仅写 WARN 会匹配行中其他位置。"),
    ("streams", "streams", "标准输入输出流", "bash:Redirections",
     "进程通常通过三个约定的描述符通信：0 为标准输入，1 为标准输出，2 为标准错误。屏幕上混在一起的文字可能来自不同流。文件参数与标准输入也不是同一概念。",
     "`wc -l < notes.txt` 让文件成为标准输入；`wc -l notes.txt` 把路径作为参数交给 wc。二者读相同内容，但输出中的文件名可能不同。",
     "看到输出都在终端，就认为标准输出和标准错误是一条流。", "为何命令的普通结果和错误信息可以分别写入两个文件？",
     "它们通常使用不同描述符：1 是标准输出，2 是标准错误；Shell 可分别重定向。"),
    ("redirect", "streams", "覆盖输出重定向", "bash:Redirecting-Output",
     "默认未启用 noclobber 时，> 将标准输出写入目标，已有目标会先被截断。重定向由 Shell 在执行命令前设置，因此不能用 cat file > file 原地保留内容。",
     "`printf '%s\\n' 'hello' > greeting.txt` 新建或覆盖 greeting.txt；终端没有显示 hello，不代表命令没有运行。",
     "以为 > 会等命令读取完输入后才清空目标。", "为什么 cat notes.txt > notes.txt 可能把原内容清空？",
     "Shell 通常在启动 cat 前打开并截断目标，而输入和目标是同一文件。应写到另一个文件后再核对。"),
    ("append", "streams", "追加输出重定向", "bash:Appending-Redirected-Output",
     ">> 把标准输出追加到文件末尾；文件不存在时可创建。与 > 的覆盖行为不同，追加不会自动添加记录分隔符，换行应由输出命令提供。",
     "连续两次执行 `printf '%s\\n' 'done' >> progress.log`，通常得到两行 done。",
     "把 >> 和 > 当成等价写法。", "要保留现有日志并加一行 done，应选择 > 还是 >>？",
     "选择 >>，例如 printf '%s\\n' 'done' >> progress.log；printf 负责输出换行，重定向负责追加。"),
    ("stderr", "streams", "标准错误重定向", "bash:Duplicating-File-Descriptors",
     "2> 将标准错误写到文件。2>&1 把描述符 2 指向当时描述符 1 指向的位置；重定向按从左到右处理，因此排列顺序会改变最终去向。",
     "`cmd > out.log 2>&1` 将两条输出流汇入 out.log；`cmd 2>&1 > out.log` 通常只把标准输出写入文件，标准错误仍去原标准输出位置。这里 cmd 是占位命令。",
     "认为所有重定向排列顺序都无关紧要。", "cmd > both.log 2>&1 与 cmd 2>&1 > both.log 的标准错误去向相同吗？",
     "通常不同。前者复制已指向文件的描述符 1；后者先复制原来的描述符 1，再单独把 1 改到文件。"),
    ("pipe", "streams", "管道", "bash:Pipelines",
     "普通管道 | 把左侧命令的标准输出接到右侧命令的标准输入。传递的是数据流，不是自动传递文件名参数。标准错误默认不经过普通管道。",
     "`grep -F 'ERROR' app.log | wc -l` 先筛选错误行，再数这些行；wc 读取管道输入。",
     "以为右侧命令获得的是左侧文件路径，或所有错误都会流入管道。", "grep -F 'ERROR' app.log | wc -l 数的是文件总行数还是匹配行数？",
     "数匹配行数，wc 接收的是 grep 输出的文本行。grep 的标准错误默认不会进入这个普通管道。"),
    ("sort", "streams", "sort 排序", "core:sort-invocation",
     "sort 对输入行排序后写到标准输出，默认不改变源文件。默认排序受区域设置影响；-n 按数值比较。应根据数据含义选择排序方式。",
     "文本行 10、2、1 在 C 区域的字典序下为 1、10、2；`sort -n` 的结果为 1、2、10。",
     "数字看起来像数字，就认为默认按数值排序。", "要把每行一个数的 scores.txt 从小到大排序，应加什么选项？",
     "使用 sort -n scores.txt；它把排序结果写到标准输出，默认不覆盖 scores.txt。"),
    ("uniq", "streams", "uniq 相邻重复行处理", "core:uniq-invocation",
     "uniq 合并相邻的重复行，-c 统计每组相邻重复次数。若要统计全文件相同文本的出现次数，可先排序让相同行相邻，但排序会改变原顺序。",
     "输入 A、B、A 时直接 uniq 仍有三行；先 sort 再 uniq 可得到 A、B 两行。",
     "认为 uniq 会自动找出全文件所有重复行。", "输入 A、B、A 直接经过 uniq 会得到几行？怎样统计每种行的次数？",
     "仍是三行，因为重复 A 不相邻。可用 sort names.txt | uniq -c 统计，但原始顺序会丢失。"),
    ("wc", "streams", "wc 文本计数", "core:wc-invocation",
     "wc 默认报告换行数、词数和字节数。-l 数换行符，-c 数字节，-m 数字符，不能在多字节文本中混用。最后一段没有换行时，-l 不把它算作一个换行。",
     "`printf 'abc' | wc -l` 输出 0；`printf 'abc\\n' | wc -l` 输出 1。中文字符的字节数可能大于字符数。",
     "把 wc -l 当作不考虑结尾换行的可见行计数。", "printf 'hello' | wc -l 的结果是多少，为什么？",
     "是 0，因为 printf 未输出换行符，而 wc -l 统计换行符数量。"),
    ("identity", "permissions", "用户与组身份", "core:id-invocation",
     "Linux 使用用户 ID 和组 ID 表示身份。文件有属主和属组，进程的有效身份参与权限判断。id 可查看当前用户及组信息；用户名相似不代表权限相同。",
     "运行 `id`，区分 uid、gid 和附加组。读取他人文件是否允许，还要结合文件及沿途目录权限。",
     "认为只要知道文件名就一定可以读取。", "权限判断为什么既需要身份信息，也需要目标的权限信息？",
     "身份决定适用属主、组或其他用户的权限类别；权限位以及目录访问条件决定能做什么，不能只看名称。"),
    ("file_permissions", "permissions", "普通文件权限", "core:Mode-Structure",
     "传统模式位分别给属主、组、其他用户设置 r、w、x。对普通文件，r 允许读取内容，w 允许写内容，x 允许尝试执行。执行还要求格式、解释器等条件成立。ACL 等机制可能进一步影响结果。",
     "普通文件模式 rw-r----- 表示属主可读写、组可读、其他无权限。没有 x 时不能仅靠 ./file 直接执行。",
     "以为 x 保证文件一定能成功执行。", "普通文件 rw-r----- 的属组成员能否按这些传统权限位修改内容？",
     "不能；组类别只有 r，没有 w。本题假定没有 ACL 等额外授权。"),
    ("directory_permissions", "permissions", "目录权限", "core:Mode-Structure",
     "对目录，r 用于列出名称，x 用于搜索或穿越，w 用于修改目录项，通常还需 x 配合。删除文件名主要取决于父目录的权限，并受 sticky bit 等规则约束，不等同于文件内容可写。",
     "对目录只有 x 而无 r 时，在其他条件允许下可访问已知名称，但不能列出目录名称清单。",
     "认为目录的 r、w、x 和普通文件的意义完全一致。", "文件没有写权限，是否就一定无法删除这个文件名？",
     "不一定。删除目录项主要检查父目录的写和搜索权限，还可能受 sticky bit、只读文件系统等约束；文件内容写权限不是唯一条件。"),
    ("chmod", "permissions", "chmod 修改模式位", "core:chmod-invocation",
     "chmod 修改模式位，可使用符号形式或八进制形式。r、w、x 分别对应 4、2、1；u、g、o 分别代表属主、组、其他。只为任务增加必要权限，避免用 777 掩盖问题。",
     "`chmod u+x report.sh` 给属主增加执行位；`chmod 640 notes.txt` 设置属主读写、组只读、其他无权限。",
     "权限错误一律用 chmod 777 解决。", "chmod 640 notes.txt 分别授予属主、组、其他什么权限？",
     "6=4+2，属主读写；4 为组只读；0 为其他无权限。没有给任何类别执行位。"),
    ("process", "processes", "进程", "man:proc_pid",
     "进程是程序的一次运行实例，具有 PID、工作目录、打开的文件描述符和运行状态。同一程序可以有多个进程。PID 会被系统重新使用，不应把很久以前记录的 PID 当成永远有效。",
     "同时启动两个 sleep，会出现两个运行实例，即使它们来自同一个程序。具体 PID 由本次系统运行决定。",
     "把磁盘上的程序文件等同于正在运行的进程。", "同一个程序运行两次，是否必然共享一个 PID？",
     "不是；独立启动通常形成不同进程和 PID。PID 标识运行实例，不是程序文件名。"),
    ("ps", "processes", "ps 进程快照", "man:ps",
     "ps 展示调用时的进程信息快照。选择选项会改变显示范围，-p 可按 PID 查询，-o 可指定列。不能把一次快照理解为持续监控，也不能把进程名称当唯一身份。",
     "`ps -p PID -o pid,ppid,stat,comm` 按实际 PID 查询进程；PID 是需要替换的占位符，不是字面命令参数。",
     "以为 ps 输出会自动持续刷新。", "要确认一个 PID 对应哪个进程，为什么应同时查看命令和状态？",
     "PID 可能复用，进程也可能已经退出或变换状态；应核对当前快照中的 PID、命令及状态，不能只凭旧记录操作。"),
    ("signal", "processes", "进程信号", "man:signal",
     "信号用于通知进程事件。TERM 通常请求终止，程序可捕获并清理；KILL 不能被捕获或忽略。kill 这个命令负责发送信号，不保证任意信号都会立即终止目标。",
     "对自己创建的练习进程，先核对 PID，再用 `kill -TERM PID` 请求退出，之后重新检查。不要把示例 PID 用于未知进程。",
     "认为 kill 只能发送 KILL，或一开始就必须使用 -9。", "为什么正常停止程序通常先考虑 TERM 而不是 KILL？",
     "TERM 允许程序进行退出处理，KILL 不给程序清理机会；具体是否退出仍取决于程序行为及状态。"),
    ("jobs", "processes", "Shell 作业控制", "bash:Job-Control-Basics",
     "交互式 Bash 可把一个管道作为作业管理。& 后台启动，jobs 显示当前 Shell 的作业，fg 恢复前台；Ctrl-Z 通常暂停前台作业。作业号与系统 PID 不是同一编号。",
     "在专用终端运行 `sleep 30 &`，用 `jobs` 查看，再用 `fg` 带回前台，按 Ctrl-C 结束自己的练习任务。",
     "把暂停理解为结束，或把后台运行当作永久脱离终端。", "Ctrl-Z 后的程序与正常退出的程序有什么区别？",
     "前者通常处于停止状态，仍是可恢复的作业；退出表示进程已结束。后台或暂停也不自动保证关闭终端后继续运行。"),
    ("variable", "scripts", "Shell 变量", "bash:Shell-Parameters",
     "Bash 变量用 name=value 赋值，等号两边不能随意加空格。读取常用 $name 或 ${name}。传递可能含空格的值时使用双引号。普通 Shell 变量不会自动成为子进程的环境变量。",
     "`name='my notes'` 后用 `printf '%s\\n' \"$name\"` 输出；`export name` 才把它标记为向后续子进程传递的环境变量。",
     "认为 name = value 与 name=value 等价，或变量赋值自动导出。", "变量 name 的值含空格，传给 ls 时怎样保证仍是一个参数？",
     "使用 ls -- \"$name\"；双引号保护展开结果中的空格，-- 结束 GNU ls 的选项解析。"),
    ("exit_status", "scripts", "退出状态", "bash:Exit-Status",
     "命令返回退出状态，约定 0 表示成功，非零表示其他结果。$? 表示最近命令状态，应及时读取。grep 的 1 表示没有匹配，不应一概当作程序崩溃；管道状态还受 pipefail 影响。",
     "运行 `grep -F 'ERROR' app.log` 后立即检查 `printf '%s\\n' \"$?\"`。默认情况下，管道一般返回最后一个命令的状态。",
     "把非零状态一概当成同一种错误，或认为管道中任一步失败都自动反映在最终状态。", "默认未启用 pipefail 时，false | true 的状态是什么？",
     "通常为 0，因为最后一个命令 true 成功。启用 pipefail 会改变管道状态规则，不能把默认状态当全部步骤成功的证明。"),
    ("for_loop", "scripts", "for 循环", "bash:Looping-Constructs",
     "for 依次把列表中的项赋给变量，并执行 do 与 done 之间的命令。循环处理文件名时仍要保护空格；列表成员个数与文本字符个数不是同一回事。",
     "`for file in 'a one.txt' 'b.txt'; do printf '%s\\n' \"$file\"; done` 循环两次，分别输出两个完整文件名。",
     "以为含空格的一个带引号文件名会循环两次。", "for file in 'a one.txt' 'b.txt' 的循环体执行几次？",
     "两次。列表有两个词，a one.txt 被引号保护为一个词；在循环体中引用变量也应使用双引号。"),
    ("script", "scripts", "Bash 脚本", "bash:Shell-Scripts",
     "脚本将命令保存为可重复执行的文本。bash file.sh 指定解释器读取文件；./file.sh 直接执行时需要可执行权限和适当的解释器声明。脚本接收位置参数，应按任务检查输入。",
     "脚本首行可写 `#!/usr/bin/env bash`，后续用 `printf '%s\\n' \"$1\"` 输出首个参数。`bash show.sh 'my notes'` 传入一个位置参数。",
     "认为 bash file.sh 与 ./file.sh 对执行权限的要求完全相同。", "文件可读但没有执行位，bash show.sh 与 ./show.sh 是否一定都能运行？",
     "不一定。bash show.sh 由解释器读取可读文件，不要求文件自身执行位；./show.sh 需要执行权限，还需有效解释器等条件。"),
]

# Each dependency is justified by the target learning task, not chapter order.
PREREQUISITES = [
    ("shell", "syntax", "区分解释器和程序后，才能解释命令名与参数如何交给程序。"),
    ("syntax", "help", "检索帮助需先识别命令名和选项，才知道要查哪个对象。"),
    ("syntax", "quoting", "引号任务要求解释参数数量变化，需要先理解参数。"),
    ("cwd", "relative", "相对路径解析必须知道从哪个工作目录开始。"),
    ("absolute", "cd", "目录切换任务包含绝对路径定位，需要先确定根起点。"),
    ("relative", "cd", "目录切换任务包含 .. 和相对位置，需先会逐段解析。"),
    ("syntax", "ls", "列出目录项任务需区分 -l、-d 选项与路径操作数。"),
    ("relative", "mkdir", "创建嵌套目录前需判断目标相对于当前位置的位置。"),
    ("relative", "cp", "复制任务要求明确源路径和目标路径，避免复制到错误位置。"),
    ("relative", "mv", "重命名和移动任务需解释源、目标路径的变化。"),
    ("relative", "rm", "删除前必须能核对所写路径指向的目录项。"),
    ("relative", "symlink", "解释相对链接目标需先理解相对路径的解析起点。"),
    ("relative", "tar", "打包任务需区分归档路径与被打包目录的位置。"),
    ("relative", "cat", "查看文本前需能指定输入文件的路径。"),
    ("quoting", "glob", "通配展开的自检要求区分引用与未引用的模式。"),
    ("glob", "find", "find 名称匹配任务要求解释为何不能让 Shell 提前展开模式。"),
    ("quoting", "grep", "筛选任务需要把完整固定字符串作为一个模式参数传入。"),
    ("grep", "regex", "本课通过 grep -E 应用正则，需先理解按行筛选的目标。"),
    ("streams", "redirect", "覆盖输出任务需识别被重定向的标准输出。"),
    ("streams", "append", "追加输出任务需明确内容来自标准输出，换行由程序产生。"),
    ("redirect", "stderr", "描述符复制顺序任务先使用 > 设置标准输出目标。"),
    ("streams", "pipe", "管道依赖标准输出接到标准输入的通信模型。"),
    ("syntax", "sort", "排序自检需根据 -n 选项区分文本与数值比较。"),
    ("sort", "uniq", "本节点要求解释全文件计数时排序使相同行相邻的作用。"),
    ("syntax", "wc", "计数任务必须区分 -l、-c、-m 各自统计什么。"),
    ("identity", "file_permissions", "应用属主、组、其他权限前需理解用户与组身份。"),
    ("identity", "directory_permissions", "判断目录访问时需明确进程适用哪类身份权限。"),
    ("file_permissions", "chmod", "普通文件授权需先会解释目标模式位。"),
    ("directory_permissions", "chmod", "本课的最小授权目标包括目录，需先知道目录位的独立含义。"),
    ("process", "ps", "读进程快照前需要区分运行实例、程序和 PID。"),
    ("ps", "signal", "本课发送信号前要求通过快照核对目标 PID 与命令。"),
    ("process", "jobs", "解释暂停、前后台和退出需先理解进程生命周期。"),
    ("quoting", "variable", "变量任务要求保持含空格的展开结果为一个参数。"),
    ("variable", "exit_status", "读取 $? 及及时保存状态需理解 Shell 参数展开。"),
    ("variable", "for_loop", "循环依次赋值并读取循环变量，需要先掌握变量引用。"),
    ("chmod", "script", "比较 bash file.sh 与 ./file.sh 需要理解执行位。"),
    ("variable", "script", "脚本练习通过引用位置参数传递文件名，需先理解参数展开。"),
]
CONFUSABLE = [
    ("absolute", "relative", "两者的路径起点不同：根目录与当前工作目录。"),
    ("cp", "mv", "复制通常保留源路径，成功移动通常撤去源路径。"),
    ("grep", "find", "前者匹配文本内容，后者遍历文件树筛选目录项。"),
    ("glob", "regex", "文件名通配与文本正则的语法、解释者及作用对象不同。"),
    ("redirect", "append", "同为写输出，> 通常截断，>> 保留旧内容并追加。"),
    ("file_permissions", "directory_permissions", "同一 r/w/x 标记对文件内容和目录项有不同操作语义。"),
    ("process", "jobs", "系统 PID 标识进程，Shell 作业号属于当前 Shell 的作业表。"),
    ("symlink", "cp", "符号链接保存路径，复制生成内容副本。"),
]
RELATED = [
    ("shell", "cwd", "Shell 进程的工作目录为相对路径提供上下文。"),
    ("shell", "process", "交互式 Shell 本身也是运行中的进程。"),
    ("ls", "file_permissions", "ls -l 的长格式可用于观察普通文件的权限。"),
    ("ls", "directory_permissions", "ls -ld 可查看目录本身的模式位。"),
    ("mkdir", "directory_permissions", "创建和访问目录涉及父目录和新目录权限。"),
    ("rm", "directory_permissions", "删除目录项与父目录的写及搜索权限有关。"),
    ("tar", "cp", "归档和复制都是组织备份素材的方法，产物形态不同。"),
    ("cat", "pipe", "cat 的标准输出可接入后续文本处理程序。"),
    ("grep", "pipe", "grep 筛出的行可通过管道交给其他程序。"),
    ("find", "relative", "find 的遍历起点可由相对路径指定。"),
    ("pipe", "wc", "wc 可统计管道输入的数据，无需文件参数。"),
    ("pipe", "uniq", "sort 与 uniq 可用管道组合，但这一组合不是所有 uniq 用法的前置条件。"),
    ("pipe", "exit_status", "整个管道的退出状态还取决于最后一个命令和 pipefail 设置。"),
    ("signal", "jobs", "交互式作业控制会借助信号暂停、继续或终止进程。"),
    ("for_loop", "script", "循环可以写入脚本，但简单脚本并不必须含循环。"),
]


def documentation(spec):
    family, slug = spec.split(":", 1)
    if family == "lab":
        return "LinuxLab 任务契约", "https://github.com/Southwall-Tester/LinuxLab/blob/main/" + slug, "CONTRACTS / requirements / configuration validation"
    if family == "vim":
        return "Vim 用户手册：入门", "https://vimhelp.org/usr_02.txt.html", "02.2 Inserting text / 02.4 Saving and exiting"
    redirections = {"Redirecting-Output", "Appending-Redirected-Output", "Duplicating-File-Descriptors"}
    if family == "bash" and slug in redirections:
        return f"GNU Bash：{slug}", "https://www.gnu.org/software/bash/manual/html_node/Redirections.html#" + slug, slug.replace("-", " ")
    if family in {"bash", "core", "grep", "find", "tar"}:
        project = {"core": "coreutils", "find": "findutils"}.get(family, family)
        base = f"https://www.gnu.org/software/{project}/manual/"
        if family == "find":
            base += "html_node/find_html/"
        else:
            base += "html_node/"
        return f"GNU {project}：{slug}", base + slug + ".html", slug.replace("-", " ")
    if family == "carp":
        return "Software Carpentry：Navigating Files and Directories", f"https://swcarpentry.github.io/shell-novice/{slug}.html", "Navigating Files and Directories / paths"
    section = {"proc_pid": "5", "ps": "1", "signal": "7", "top": "1"}[slug]
    name = "proc_pid" if slug == "proc_pid" else slug
    return f"Linux manual：{name}({section})", f"https://man7.org/linux/man-pages/man{section}/{name}.{section}.html", f"{name}({section}) DESCRIPTION"


def build():
    sources, by_spec, nodes = [], {}, []
    for ident, chapter, title, spec, explanation, example, mistake, question, answer in NODES + lab_curriculum.NODES:
        if spec not in by_spec:
            source_id = "source_" + str(len(sources) + 1).zfill(2)
            by_spec[spec] = source_id
            label, url, locator = documentation(spec)
            sources.append(dict(id=source_id, title=label, kind="reference_documentation", url=url, locator=locator))
        source_id = by_spec[spec]
        source = next(s for s in sources if s["id"] == source_id)
        nodes.append(dict(
            id=ident, chapter_id=chapter, title=title, description=explanation,
            objectives=[f"解释{title}的行为，并独立回答本节点情境题。"],
            aliases=[], misconception=mistake, source_ids=[source_id], review_status="draft",
            check_question=question, expected_answer=answer,
            check_task=dict(id="check_" + ident, version=1, rubric=[answer, "说明理由，并区分题目给定条件与自己的假设。"],
                            hint_levels=["先定位题目中涉及的对象、输入和预期结果。", "注意这个常见误解：" + mistake,
                                         "回到概念：" + explanation, "关键要点：" + answer]),
            lesson_content=[dict(id="concept", heading="概念与边界", text=explanation),
                            dict(id="example", heading="操作示例", text=example),
                            dict(id="check", heading="停下来检验", text=question),
                            dict(id="source", heading="参考来源", text=f"本节为自编中文教学材料，技术依据：[查看文档]({source['url']})。先修关系为本课教学设计，待教师核验。")],
            provenance=dict(kind="agent_authored", policy_version=POLICY, human_review=False),
            evidence_refs=[dict(source_id=source_id, locator=next(s["locator"] for s in sources if s["id"] == source_id),
                                lesson_section_id="concept", interpretation="自编解释；来源链接是技术核验入口，非逐字引文。")],
        ))
    index = {n["id"]: n for n in nodes}
    edges = []
    for kind, rows in [("prerequisite", PREREQUISITES + lab_curriculum.PREREQUISITES), ("confusable", CONFUSABLE), ("related", RELATED + lab_curriculum.RELATED)]:
        for a, b, reason in rows:
            edges.append(dict(id=f"{kind}_{a}_{b}", source=a, target=b, type=kind, reason=reason,
                              source_ids=list(dict.fromkeys(index[a]["source_ids"] + index[b]["source_ids"])),
                              review_status="draft", basis_kind="authored_teaching_dependency" if kind == "prerequisite" else "authored_semantic_comparison",
                              evidence_refs=[dict(node_id=k, lesson_section_id="concept") for k in (a, b)],
                              policy_version=POLICY))
    resources = [dict(id="resource_" + source["id"], title=source["title"], organization="The Carpentries" if "Carpentry" in source["title"] else "GNU Project" if source["title"].startswith("GNU") else "Vim project" if source["title"].startswith("Vim") else "LinuxLab project" if source["title"].startswith("LinuxLab") else "Linux manual authors / man7.org",
                      url=source["url"], applicable_segment=source["locator"], format="lesson",
                      node_ids=[n["id"] for n in nodes if source["id"] in n["source_ids"]],
                      prerequisite_ids=[], source_ids=[source["id"]], review_status="draft") for source in sources]
    graph = dict(schema_version=1, id=COURSE_ID, title="Linux 命令入门：从路径到 Shell 自动化", version=1,
                 overview=f"面向初学者的 8 单元课程：{len(nodes)} 个知识点，逐点中文解释、操作示例、自检题、评分参考与来源。配套 LinuxLab 九关真实终端实训；图谱与教学材料由智能体编写，等待教师审核。",
                 created_at="2026-10-10T00:00:00Z", delivery_mode="formal",
                 presentation=dict(label="自编课程 · 待审核", description="8 个单元，从路径定位到文本管道、权限、进程和 Shell 脚本；逐点提供例子与自检。"),
                 chapters=[dict(id=i, title=t, description=d) for i,t,d in CHAPTERS],
                 nodes=nodes, edges=edges, sources=sources, resources=resources,
                 activities=[lab_curriculum.activity()],
                 review_policy=dict(intervals_days=[1,7,30]),
                 authoring=dict(kind="agent_authored", policy_version=POLICY, human_review=False,
                                environment="Linux + Bash + GNU coreutils；命令版本和环境条件以节点说明及本机手册为准。",
                                execution="内容与题目，不提供平台内任意 Shell 执行器。", scope="入门命令；网络服务、包管理及高级 sed/awk 留待后续课程。"))
    validate_graph(graph)
    audit = dict(policy_version=POLICY, method="agent_authored_curriculum_audit", human_review=False,
                 decisions=[dict(node_id=n["id"], term=n["title"], admitted=True, atomic=True, domain_status="lab_application_data_concept" if n["id"] in ("config_record", "log_record") else "linux_shell_concept_or_command",
                                 reason="本条只定义一个概念或一个命令的职责；命令选项作为该命令的属性，不拆成无语境节点。",
                                 evidence_refs=n["evidence_refs"]) for n in nodes],
                 rejected=[dict(term="Linux 基础", reason="课程范围标签，非原子概念。"),
                           dict(term="查看与查找", reason="教学单元标签，不作为概念节点。"),
                           dict(term="文本三剑客", reason="多个工具的集合昵称，应按独立工具与知识目标拆分。")],
                 relation_policy="只在获准概念间建立关系；先修来自当前任务所需能力，非标题顺序；相关和易混淆边不约束学习顺序。")
    return graph, audit


def main():
    graph, audit = build()
    DEST.mkdir(parents=True, exist_ok=True)
    for name, value in [("course.json", graph), ("term-audit.json", audit)]:
        (DEST / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"course_id": graph["id"], "nodes": len(graph["nodes"]), "edges": len(graph["edges"]), "sources": len(graph["sources"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
