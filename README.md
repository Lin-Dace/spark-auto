# spark-auto：抖音 / 快手每日续火花工具

个人自用的小工具：每天在设定时间窗口内随机挑一个时刻，给指定好友发送固定的「早上好」表情（表情面板不可用时回退到文案）续火花。

仅限**自己的账号、自己的好友、单人单机使用**。不做多账号托管、不做批量营销、不绕验证码、不逆向接口。若平台给出验证码、频繁提示或限制私信，工具会立即停止并在日志里写明原因。

## 一、环境准备

- Python 3.10+
- 浏览器：优先复用本机已安装的 Chrome/Edge（`config.json` 的 `browser_channel` 设为 `chrome` 或 `msedge`）；没有时会自动降级到 Playwright 自带 Chromium

Windows 用户直接双击 `setup.bat`，脚本会自动完成下面三步，并在缺少 `friends.json` 时从示例复制一份。

手动安装：

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

`browser_channel` 留空表示只使用 Playwright 自带 Chromium，此时必须先执行上面第二条命令。

## 二、目录结构

```
spark-auto/
├── main.py                   # 命令行入口：login / run / schedule
├── config.json               # 时间窗口、平台开关、文案池、重试次数等
├── friends.example.json      # 好友配置示例（复制为 friends.json 后填写）
├── friends.json              # 你自己的好友名单（已被 .gitignore 忽略）
├── setup.bat                 # 一键安装依赖与浏览器
├── login.bat                 # 扫码登录
├── run.bat                   # 立即执行一轮
├── install_task.ps1          # 注册 Windows 每日计划任务
├── requirements.txt
├── LICENSE
├── .gitignore
├── README.md
├── spark/
│   ├── config.py             # 配置加载与校验、好友去重
│   ├── logging_setup.py      # logs/spark.log（自动轮转）
│   ├── records.py            # records/sent.jsonl 发送记录与今日判重
│   ├── humanize.py           # 随机延时、随机文案
│   ├── browser.py            # 浏览器上下文、扫码登录、登录态保存
│   ├── runner.py             # 发送调度、失败分类、立即停止
│   └── platforms/
│       ├── base.py           # 通用发送流程 + 弹性定位 + 异常类型
│       ├── douyin.py         # 抖音网页版私信
│       └── kuaishou.py       # 快手网页版私信
├── state/                    # 运行后生成：storage_state.{platform}.json
├── logs/                     # 运行后生成：spark.log
└── records/                  # 运行后生成：sent.jsonl
```

## 三、填写好友与首次登录

1. 复制 `friends.example.json` 为 `friends.json`，把示例名字换成自己的好友（名字要和私信会话列表完全一致）。
2. 双击 `login.bat`，或执行：

```powershell
python main.py login --platform douyin
```

只有同时启用快手时才需要 `--platform all`。

会弹出有头浏览器，扫码登录成功后**自动检测并保存**（最多等 5 分钟），登录态写入 `state/storage_state.douyin.json`。
之后运行默认用这份登录态，不保存账号密码。**这个文件等价于账号凭证，不要提交到 Git、不要发给别人。**

只登录某个平台：

```powershell
python main.py login --platform douyin
```

## 四、运行方式

立即执行一轮（当天已发送的好友自动跳过）：

```powershell
python main.py run
```

先等到今天的随机时刻再执行一轮（配合计划任务，不占常驻进程）：

```powershell
python main.py run --random
```

常驻运行，每天在随机时间执行一次：

```powershell
python main.py schedule
```

用 Windows 计划任务每天唤醒一次，再由程序自己等到随机时刻（在项目目录执行）：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_task.ps1
```

默认每天 07:50 启动，可用 `-Time "09:00"` 修改。`install_task.ps1` 会自动取当前 Python 的完整路径，不需要手改路径。

（计划任务只在电脑开机且已登录时才会执行；07:50 时电脑没开，当天就会跳过。删除任务：`schtasks /Delete /TN "SparkAuto" /F`。）

日常也可以直接双击 `run.bat` 手动跑一轮。

## 五、配置说明（config.json）

| 字段 | 说明 |
| --- | --- |
| `send_window.start` / `end` | 每日允许发送的时间范围，如 `08:00`-`22:00`，不支持跨零点 |
| `send_window.jitter_seconds` | 时间抖动（秒），在随机时刻基础上再做 ± 抖动，并夹在窗口内 |
| `friend_interval_seconds.min/max` | 好友之间的随机间隔，默认 5-60 秒 |
| `max_retries` | 仅针对“页面操作/网络抖动”这类可重试失败的最大重试次数（不含首次）。结构异常、无法确认结果时不重试，避免重复发送 |
| `headless` | 是否无头运行。抖音实测无头模式容易触发「验证码中间页」，建议保持 `false`；扫码登录始终是有头模式 |
| `browser_channel` | `chrome` / `msedge` 复用本机浏览器；留空则用 Playwright 自带 Chromium |
| `sticker_enabled` | 是否优先发表情包。`true` 时发送固定的「早上好」贴图，面板不可用才回退到文案；`false` 则只发文案 |
| `sticker_resource_id` | 「早上好」贴图的资源 ID，用于在表情面板里定位；贴图换了改这里 |
| `sticker_fallback_index` | 按资源 ID 找不到时的兜底序号（表情面板里第几个），默认 12 |
| `platforms.douyin.enabled` | 抖音开关 |
| `platforms.douyin.messages_url` | 抖音私信页地址，页面改版时可改 |
| `platforms.kuaishou.enabled` | 快手开关 |
| `platforms.kuaishou.messages_url` | 快手私信页地址 |
| `message_pool` | 文案池，至少一条；每次随机抽取，并尽量避开该好友上一条文案 |

`friends.json` 保存你自己的好友名单，**已被 `.gitignore` 忽略，不要提交**。第一次使用时从 `friends.example.json` 复制一份。按平台分开填，条目可以是对象，也可以直接写字符串：

```json
{
  "douyin": [
    {"name": "张三", "user_id": "", "enabled": true},
    "李四"
  ],
  "kuaishou": [
    {"name": "王五", "enabled": true}
  ]
}
```

- `name`：要和页面里显示的名字一致（搜索和聊天列表都用它定位）
- `user_id`：可选，填了就作为发送记录的唯一标识；不填则用名字
- `enabled: false`：临时停发这个好友
- 同名/同 `user_id` 的好友会自动去重，并在日志里提示

## 六、日志与发送记录

- `logs/spark.log`：每次执行的时间、平台、成功/失败/跳过及原因，超过 2MB 自动轮转
- `records/sent.jsonl`：发送成功后追加一行，字段为 `platform`（平台）、`friend_key`（好友标识）、`friend_name`、`sent_at`（发送时间）、`message`（文案或 `[早上好表情包]`）

判断“今天是否已发过”只读这个文件，所以删除它等于允许当天重发。

## 七、失败与停止策略

| 情况 | 行为 |
| --- | --- |
| 页面出现验证码 / 安全验证 / 操作频繁 / 发送失败等提示 | 立即中止整轮，写入日志，当天不再反复尝试 |
| 登录态失效（页面出现扫码登录） | 跳过该平台剩余好友，提示重新执行 `login` |
| 找不到搜索框、输入框、发送按钮 | 判定为页面结构变化，记录原因并跳过该好友，不伪造请求 |
| 点击发送后无法确认结果 | 记录“无法确认”，不写发送记录、不重试（防止重复发送） |
| 浏览器/网络抖动 | 最多重试 `max_retries` 次，之后跳过 |

## 八、页面改版了怎么维护

所有选择器都集中在 `spark/platforms/douyin.py`、`spark/platforms/kuaishou.py`，并按“语义化 → placeholder → 通用可编辑框”的顺序降级：

1. 先看日志里的失败原因，例如“找不到聊天输入框”
2. 用 `python main.py login --platform douyin` 打开有头浏览器，手动进到私信页
3. F12 检查真实元素的 `placeholder`、`role`、`contenteditable` 等属性
4. 把更准确的选择器加到对应候选列表的**最前面**，保留原有候选作为兜底

排查时建议先把 `config.json` 里的 `headless` 改成 `false`，直接观察浏览器里的实际动作；再只留一个测试好友，确认没问题后恢复。

## 九、已知限制

- 抖音私信页地址是 `https://www.douyin.com/chat`（旧的 `/messages` 已返回 404）；页面改版时只需改 `config.json`。
- 抖音无头模式实测会触发「验证码中间页」，所以默认使用有头模式。
- 快手网页版实测没有私信能力：登录后首页导航无「消息」，`/message`、`/chat`、`/login` 均为 404，用户主页只有「关注」没有「私信」。因此快手默认关闭，日志会记「没有可用私信入口」并跳过。
- 默认通过网页版表情面板发送固定的「早上好」贴图，不支持图片/视频；表情面板找不到或结构变化时自动回退到文案。
- 贴图通过 `sticker_resource_id` 定位，面板顺序变化时改 `config.json` 即可，不用改代码。
- 表情面板的 DOM 选择器（`.componentsemojiemojiPanel`、`.emojiEmojiItememojiItem`）比文字输入更容易随改版失效，失效时只影响表情包，不影响文字兜底。
- 只支持同一个时间窗口的每日一次；跨零点窗口不支持。
- 好友名必须和页面显示一致，改名后需要同步修改 `friends.json`。

## 十、分享给别人使用与隐私

这个项目从设计上就是「谁用谁本地登录」，没有服务器、没有上传接口、没有任何回传：

- 扫码得到的登录态只写在使用者自己电脑的 `state/` 下，等价于账号凭证，不会发送给任何人。
- `friends.json`、`state/`、`logs/`、`records/` 都在 `.gitignore` 里，不会被提交，也不会随仓库分发。
- 你把项目发给别人时，**不要打包自己的 `state/` 和 `friends.json`**；对方拿到的是干净代码，用他自己的账号扫码。

对方的完整流程：

1. 双击 `setup.bat` 安装依赖和浏览器
2. 把 `friends.example.json` 复制为 `friends.json`，填自己的好友
3. 双击 `login.bat`，用自己的抖音扫码
4. 双击 `run.bat` 测试，确认无误后运行 `install_task.ps1` 注册每日任务

对方电脑需要 Python 3.10+；没有 Chrome/Edge 时，`setup.bat` 会装好 Playwright Chromium，程序启动失败也会自动降级。

使用本工具产生的账号风险由使用者自行承担，请遵守平台规则，仅对自己的账号和好友低频使用。

## 许可证

[MIT](LICENSE)

## 十一、合规提醒

自动化操作可能不符合平台用户协议，账号存在被限制私信或风控的风险。本项目按“个人自用 + 低频率 + 遇到限制立即停止”设计，请勿改造成多账号群控、批量引流或营销工具，也不要用它代管他人账号。

登录态文件 `state/*.json`、日志、记录都在 `.gitignore` 中，请勿上传到任何公开仓库或网盘。
