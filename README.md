# 中控杯决赛算法工程

本仓库用于准备“中控杯”智能制造挑战赛赛题 2 决赛的选手算法服务。

最重要的原则：**三个人可以分别负责三个任务，但比赛现场必须启动同一个算法服务，给竞赛软件填写同一个 Base URL。**

## 1. 统一接口和端口

竞赛操作软件只调用以下 4 个接口：

```text
GET  /api/health
POST /api/task1/execute
POST /api/task2/execute
POST /api/task3/execute
```

本项目默认选手算法服务端口：

```text
选手算法服务: http://<工控机IP>:5000
```

现场竞赛软件的 Base URL 填：

```text
http://127.0.0.1:5000
```

如果竞赛软件和算法服务不在同一台机器上，填：

```text
http://<运行算法服务的机器IP>:5000
```

硬件默认端口约定：

```text
机械臂 FTArm B9: http://127.0.0.1:8087
灵巧手 O10:      http://127.0.0.1:8088
```

这些地址都在 `config/local.json` 里改，不要写死在任务代码里。

## 2. 项目结构

```text
app/
  server.py          # 统一 HTTP 服务入口，比赛软件只连它
  context.py         # 加载配置，初始化 arm/hand/camera

tasks/
  task1_switch.py    # 任务 1 负责人：亮灯识别 + 按钮/拨杆操作
  task2_blocks.py    # 任务 2 负责人：数字块 1->2->3->4 有序搬运
  task3_shapes.py    # 任务 3 负责人：几何体识别 + 对应槽位分拣

hardware/
  arm_client.py      # 机械臂 HTTP API 封装
  hand_client.py     # 灵巧手 HTTP API 封装
  camera_client.py   # Gemini335 相机占位封装，现场接 SDK

config/
  local.json         # 现场 IP、端口、坐标、速度、手势参数

scripts/
  run_server.sh      # 启动统一服务
  check_api.sh       # 本机快速检查 4 个比赛接口
```

## 3. Dry-run 演练模式

`config/local.json` 默认开启：

```json
"dry_run": true
```

含义：

- 不会真的请求机械臂和灵巧手。
- 三个任务接口会返回 `success=true`，用于检查统一服务、接口路径、团队代码合并是否正常。
- `ctx.arm`、`ctx.hand`、`ctx.camera` 会返回模拟结果，方便没有硬件时先写流程。

到现场接真机前，必须改成：

```json
"dry_run": false
```

**重要：正式比赛前一定确认 `dry_run=false`。否则接口会显示成功，但机器人不会动。**

## 4. 四个人怎么分工

建议 4 人分工：

```text
A: 总集成负责人
B: 任务 1 负责人
C: 任务 2 负责人
D: 任务 3 负责人
```

A 负责：

- 维护 `app/server.py`、`app/context.py`、`config/local.json`。
- 确保服务能启动，接口能被竞赛软件调用。
- 维护机械臂、灵巧手、相机公共封装。
- 合并三位任务负责人的代码。
- 现场负责启动服务、看日志、改配置、备份版本。

B 只改：

```text
tasks/task1_switch.py
```

C 只改：

```text
tasks/task2_blocks.py
```

D 只改：

```text
tasks/task3_shapes.py
```

除非和 A 约好，否则三位任务负责人不要直接改 `app/server.py`，也不要各自新开端口。

## 5. 启动和自测

启动统一算法服务：

```bash
bash scripts/run_server.sh
```

看到类似输出说明服务启动成功：

```text
Base URL: http://0.0.0.0:5000
GET  /api/health
POST /api/task1/execute
POST /api/task2/execute
POST /api/task3/execute
```

另开一个终端自测接口：

```bash
bash scripts/check_api.sh
```

`check_api.sh` 会检查：

```text
/api/health
/api/config/summary
/api/task1/execute
/api/task2/execute
/api/task3/execute
```

也可以单独测：

```bash
curl http://127.0.0.1:5000/api/health
curl http://127.0.0.1:5000/api/config/summary
curl -X POST http://127.0.0.1:5000/api/task1/execute -H "Content-Type: application/json" -d '{}'
curl -X POST http://127.0.0.1:5000/api/task2/execute -H "Content-Type: application/json" -d '{}'
curl -X POST http://127.0.0.1:5000/api/task3/execute -H "Content-Type: application/json" -d '{}'
```

当前默认 `dry_run=true`，所以三个任务接口会返回 `success=true` 和 `taskX dry-run ok`。这是为了方便没有硬件时合并测试。

## 6. 三个任务负责人要遵守的接口

每个任务文件都只需要实现一个函数：

```python
def run_task1(ctx) -> tuple[bool, str]:
    ...

def run_task2(ctx) -> tuple[bool, str]:
    ...

def run_task3(ctx) -> tuple[bool, str]:
    ...
```

返回值约定：

```text
(True, "task ok")        # 任务成功
(False, "失败原因")      # 任务失败，但服务不能崩
```

可以通过 `ctx` 使用公共资源：

```python
ctx.config   # 读取 config/local.json
ctx.arm      # 机械臂客户端
ctx.hand     # 灵巧手客户端
ctx.camera   # 相机客户端
```

例子：

```python
ctx.hand.open_hand()
ctx.arm.enable()
ctx.arm.move_pose(0.275, -0.16, 0.50, velocity_scaling=0.08)
```

建议每个任务负责人写代码时保留这三个阶段：

```python
ctx.log("task2", "started")

if ctx.dry_run:
    ctx.log("task2", "dry-run finished")
    return True, "task2 dry-run ok"

# 这里写真实视觉和硬件动作
return True, "task2 ok"
```

所有关键步骤都要写日志：

```python
ctx.log("task2", "detected blocks", blocks=blocks)
ctx.log("task2", "moving to pre-grasp", target=target)
ctx.log("task2", "finished", success=True)
```

日志会写到 `logs/YYYYMMDD.jsonl`，现场排查问题主要看这里。

## 7. 每个任务文件建议流程

任务 1：`tasks/task1_switch.py`

```text
1. 移动到任务 1 拍照位
2. 相机拍照
3. 识别哪个灯亮
4. 查对应按钮/拨杆坐标
5. 移动到预操作位
6. 设置灵巧手按压或拨动姿态
7. 执行接触动作
8. 撤离到安全位
```

任务 2：`tasks/task2_blocks.py`

```text
1. 移动到任务 2 拍照位
2. 识别 1-4 顶面数字和中心点
3. 按数字 1 -> 2 -> 3 -> 4 排序
4. 对每个长方体执行：预抓取 -> 下降 -> 抓取 -> 抬升 -> 放置 -> 释放
5. 尽量保持放置姿态与槽内姿态一致
```

任务 3：`tasks/task3_shapes.py`

```text
1. 移动到任务 3 拍照位
2. 识别几何体形状和抓取点
3. 查对应形状槽位
4. 抓取、抬升、移动、姿态校正、放置
5. 检查是否完全进入槽位边界
```

## 8. 禁止事项

- 不要在三个任务里各自启动 HTTP 服务。
- 不要改比赛接口路径。
- 不要把 `5000`、`8087`、`8088` 写散在各个任务文件里。
- 不要让任务函数抛异常到服务外层；失败要返回 `(False, "原因")`。
- 不要在没有确认 `dry_run=false` 的情况下上真机调试。
- 不要跳过安全点直接从一个任务区域横穿到另一个任务区域。

## 9. 现场调试顺序

19 号有调试时间，建议按这个顺序，不要一上来就跑完整任务：

```text
1. 启动算法服务，测试 /api/health
2. 确认机械臂地址和端口 8087
3. 确认灵巧手地址和端口 8088
4. 测机械臂 status / motors / enable
5. 测灵巧手 open / half / grip / release
6. 测 Gemini335 取图和保存图片
7. 做相机到机器人坐标标定
8. 调任务 2 的单个数字块抓取和放置
9. 调任务 2 的 1->2->3->4 完整流程
10. 调任务 1 的亮灯识别和按拨动作
11. 调任务 3 的形状识别和分拣
```

优先级建议：

```text
任务 2 > 任务 1 > 任务 3
```

任务 2 最适合打通“视觉 + 抓取 + 搬运 + 放置”完整链路。

## 10. 配置注意事项

所有现场会变的东西都放进 `config/local.json`：

- 机械臂 IP 和端口
- 灵巧手 IP 和端口
- 相机序列号/分辨率
- 安全点
- 拍照点
- 槽位坐标
- 放置坐标
- 抓取高度
- 放置高度
- 灵巧手手势
- 机械臂速度

不要把现场坐标直接写死在 `tasks/*.py` 里。现场调试时主要改配置，不要频繁改代码。

## 11. 安全注意事项

- 所有首次运动必须低速，建议 `velocity_scaling <= 0.08`。
- 机械臂执行前先检查 `status`、`motors`、`enable`。
- 直线运动返回里如果出现 `OMPL`，说明没有按直线走，可能有碰撞风险。
- 灵巧手不要长时间极限闭合，避免堵转。
- 放置/按压/拨动动作要先用小位移试探，再逐步加深。
- 碰撞比超时更严重。比赛有设备保护分，严重碰撞会导致任务失败。

## 12. 提交前检查

上场前至少确认：

```text
[ ] bash scripts/run_server.sh 能启动
[ ] /api/health 返回 success=true
[ ] /api/config/summary 里的 dryRun=false
[ ] 三个任务接口都不会让服务崩溃
[ ] config/local.json 已改成现场 IP 和坐标
[ ] logs/ 中能看到任务执行日志
[ ] 代码、配置、依赖、说明文档已复制到 U 盘/移动硬盘
[ ] 有一个冻结版本，现场临时修改前先备份
[ ] 笔记本、充电器、U 盘、标定板、网线已带
```

## 13. 资料文件

本仓库已包含比赛资料和接口文档：

- `算法与竞赛操作软件对接及说明文档.docx`
- `决赛通知（更新）：...pdf`
- `更新说明-...pdf`
- `FTArm B9 机械臂HTTP-WS 接口文档.md`
- `API接口文档.md`
- `contestant_mock_server.py`

开发时以 `README.md` 的工程约定为准；比赛规则细节以官方通知和更新说明为准。
