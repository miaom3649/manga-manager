# HManガ开发与发布

## Ubuntu 开发

Ubuntu Wayland 不允许应用自行设置顶层窗口坐标。通过 `hmanga` 命令启动时，如果检测到 Wayland 和可用的 XWayland，开发版会自动改用 Qt `xcb` 后端，以便测试弹窗居中和主窗口位置恢复；这项兼容处理不影响 Windows 成品。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,build]'
.venv/bin/python -m pytest
.venv/bin/ruff check src tests migrations
.venv/bin/hmanga
```

手机前端使用 Node.js 22：

```bash
cd frontend
npm ci
npm run lint
npm test -- --run
npm run build
```

前端正式文件会输出到 `src/hmanga/web` 并由 FastAPI 提供。

## Windows 构建

仓库的 `.github/workflows/windows-build.yml` 在 `windows-latest` 上执行 Python/前端测试、PyInstaller 和 Inno Setup，并上传安装包。

本地 Windows 构建命令：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,build]"
cd frontend
npm ci
npm run build
cd ..
.venv\Scripts\python -m PyInstaller --noconfirm packaging\HManga.spec
$process = Start-Process -FilePath "dist\HManga\HManga.exe" -ArgumentList "--version" -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Windows 成品自检失败" }
& "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe" packaging\HManga.iss
```

安装包输出到 `build-output/installer`。

安装后开始菜单有两个入口：`HManガ` 不显示控制台；`HManガ（调试）` 显示运行日志，供 Windows 测试和排错。两个入口共用同一套数据库和设置，请勿同时运行。

构建脚本会从 Inno Setup 官方源码仓库取得简体中文安装界面翻译；该翻译不包含在 Chocolatey 安装的 Inno Setup 中，因此手工直接运行 `ISCC.exe` 前也必须先运行构建脚本。

## 发布验收

- 在 Windows 10 和 Windows 11 分别验证安装、覆盖升级、托盘、彻底退出与卸载数据选择。
- 使用中文和日文路径、前导零编号、长文件名、GIF、损坏/加密/半复制 ZIP。
- 验证新增、删除、外部改名、同名替换、上传覆盖失败回滚、跨盘迁移中断和备份恢复。
- 在真实 iPhone Safari 与 Android Chrome 上验证扫码配对、再次直连、筛选、编辑、上传、两种阅读模式、断网会话缓存和凭证撤销。
- Windows 休眠跨过凌晨 2 点后验证自动备份补做；确认自动备份始终不超过 5 份。
