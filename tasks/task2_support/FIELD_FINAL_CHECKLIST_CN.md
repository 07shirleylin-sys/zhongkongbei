# 任务2赛前最终验收清单

本目录只服务任务2。现场默认采用 `fixed_slot`：相机只识别四个固定槽位中的数字，
机械臂使用每个槽位预先示教的抓取位。没有完成下列现场值时，禁止关闭 `dry_run`。

## 十项指标与实现位置

| 指标 | 当前实现 | 现场必须确定的数据 |
|---|---|---|
| 相机取图 | `orbbec_camera.py` 使用官方 `pyorbbecsdk2` 同步采集 RGB/Depth、对齐深度并保存 `.npy` | 相机序列号、可用流、SDK 深度比例 |
| 识别顶面数字 1-4 | `digits.py` + `vision.py` 对四个固定 ROI 分类并执行置信度、重复、缺失检查 | 四个 ROI；真实图片回放必须全部识别正确 |
| 定位木块中心 | `fixed_slot` 用槽位中心；`depth_robot` 用 ROI 中心邻域深度中值 | 推荐示教四个槽位抓取位；动态模式还需内外参 |
| 估计木块姿态 | 固定槽位使用每槽位标定姿态；动态模式使用配置的顶抓 RPY | 每槽位 RPY 或统一顶抓 RPY |
| 相机坐标转机械臂坐标 | `calibration.py` 执行像素+深度反投影和 4x4 外参变换 | `camera_to_robot` 外参必须用标定板验证 |
| 抓取前停位 | `pre_grasp = grasp + approach_height_m` | 拍照位、安全位、预抓高度 |
| 下降距离 | 由 `approach_height_m` 到示教抓取位，末段强制直线 | 实测避免撞槽且能夹住的高度 |
| 灵巧手闭合程度 | `grip_pose_name` 指向 10 维 `[0,1]` 手势并在预检时校验 | 实物试夹后确定 `box_grip` 10 个值 |
| 木块与末端距离 | 静态模式包含在示教抓取位；动态模式由 `grasp_z_offset_m` 修正 | 工具中心点、手指接触位置、最小安全间隙 |
| 右侧台面坐标 | `place_area.drop_points` 严格要求 4 个点并检查 `min_spacing_m` | 四个不重叠放置点、释放高度、木块尺寸加余量 |

## 推荐现场方案

1. 使用 `coordinate_mode=fixed_slot`，先不要启用动态深度抓取。
2. 机械臂移动到固定拍照位，一张图覆盖四个槽位。
3. 现场框选四个 ROI，离线重放确认 1、2、3、4 和不同排列。
4. 分别示教 `slot_a` 到 `slot_d` 的抓取位，抓取位是末端真正停止并闭手的位置。
5. 示教右侧四个放置点，间距必须大于木块最大水平尺寸加安全余量。
6. 设置机器人允许工作域；所有抓取、预抓、抬升、放置、撤离点必须在边界内。
7. 先单块低速测试，再测试四个槽位，最后测试完整 1 -> 2 -> 3 -> 4。

## 现场命令顺序

```powershell
python tasks\task2_support\check_camera_sdk.py
python tasks\task2_support\capture_camera.py config\local.json
python tasks\task2_support\replay_vision.py config\local.json --rgb <rgb.npy>
python tasks\task2_support\validate_field_config.py config\local.json
python tasks\task2_support\validate_field_config.py config\local.json --require-real
python -B -m unittest tasks.task2_support.test_support tasks.task2_support.test_executor -v
```

配置完整性检查返回 `success=true` 后，才允许进行低速真机单块测试；最终切换
`dry_run=false` 后还必须通过 `--require-real` 检查。该命令本身不会移动硬件。

U 盘 `04_校验值/TASK2_CODE_SHA256.txt` 是出发前增强前的冻结值；本轮本地增强未写回 U 盘，
最终现场版本冻结后必须重新生成校验值并单独核对。

## 真机启动门禁

```text
[ ] Orbbec Viewer 同时显示 RGB 和 Depth
[ ] SDK 检查 installed=true
[ ] 单次取图输出 RGB/Depth shape 和 depth_scale_m
[ ] 四个 ROI 不越界
[ ] 真实图片数字识别无重复、无缺失、置信度达标
[ ] photo_pose、safe_home、四个 source_slots、四个 drop_points 已示教
[ ] approach_height_m、lift_height_m、place_area.min_spacing_m 已实测填写
[ ] workspace.bounds 和 safety_margin_m 已填写
[ ] box_grip 已用实物低速验证
[ ] 单块从每个槽位都能抓起、离槽、放下
[ ] 完整 1 -> 2 -> 3 -> 4 无碰撞、无掉落
[ ] dry_run=false，Base URL 健康检查正常
[ ] 最终配置已备份，正式开始后不再修改
```
