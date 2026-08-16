# 任务2现场 U 盘清单

## 需要手动下载

截至 2026-08-16，当前 Windows x64 + Python 3.11 准备组合为：

1. Orbbec SDK v2.9.3：下载 `OrbbecSDK_v2.9.3_win64.exe`，放入
   `01_Orbbec/Windows_x64/`。
   发布页：https://github.com/orbbec/OrbbecSDK_v2/releases/tag/v2.9.3
   SHA256：`ed9d894b841714e60cd415a1ea5944d1d1fc41d2155a955f8c87beee2ca4f874`
2. Orbbec Viewer v2.9.3：在同一个发布页展开 Assets，下载 Windows x64 版本，
   放入 `01_Orbbec/Windows_x64/`。
3. Python wheel：下载
   `pyorbbecsdk2-2.1.2-cp311-cp311-win_amd64.whl`，放入
   `01_Orbbec/Windows_x64/`。
   发布页：https://github.com/orbbec/pyorbbecsdk/releases/tag/v2.1.2
   PyPI：https://pypi.org/project/pyorbbecsdk2/2.1.2/#files
   SHA256：`651a6d89177c19cfacd256e25ece21ab3ff878b4b1c98209298ebf41f0ca24a3`
4. 如果现场电脑没有 Python，下载 Python 3.11.9 Windows 64-bit installer，放入
   `01_Orbbec/Windows_x64/`：
   https://www.python.org/downloads/release/python-3119/
5. 官方 Gemini 330 系列安装说明：
   https://doc.orbbec.com/documentation/Orbbec%20Gemini%20330%20Series%20Documentation/Install%20Orbbec%20SDK

如果现场系统或 Python 版本不同，不能使用上述 wheel；必须在发布页改选匹配的
平台和 `cp38`/`cp39`/`cp310`/`cp311`/`cp312`/`cp313` 文件。

不要把 SDK、Viewer、wheel 或固件提交到 Git 仓库。

## 现场顺序

1. 确认电脑系统、x64 架构和 Python 版本。
2. 安装 Orbbec SDK v2 和 Viewer。
3. 在项目虚拟环境中离线安装 `pyorbbecsdk2` 和依赖。
4. 运行 `python tasks/task2_support/check_camera_sdk.py`。
5. 用 Viewer 验证 RGB、Depth、序列号、帧率和 USB 3.0 连接。
6. 读取相机内参、畸变参数和深度比例，写入现场标定文件。
7. 完成相机到机器人基座的外参标定，并用已知点验证误差。
8. 先低速测试一个方块，再运行完整的 1 -> 2 -> 3 -> 4 流程。

## 离线安装示例

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --no-index --find-links "<U盘>:\中控杯_Task2\01_Orbbec\Windows_x64" pyorbbecsdk2 numpy
python tasks\task2_support\check_camera_sdk.py
```

真实坐标和标定值必须写入 `03_现场数据`，不要覆盖模板。
