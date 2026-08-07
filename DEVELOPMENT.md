# H库开发与发布

## Ubuntu 开发

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,build]'
.venv/bin/python -m pytest
.venv/bin/ruff check src tests migrations
.venv/bin/hlibrary
```

手机前端使用 Node.js 22：

```bash
cd frontend
npm ci
npm run lint
npm test -- --run
npm run build
```

前端正式文件会输出到 `src/hlibrary/web` 并由 FastAPI 提供。

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
.venv\Scripts\python -m PyInstaller --noconfirm packaging\HLibrary.spec
$process = Start-Process -FilePath "dist\HLibrary\HLibrary.exe" -ArgumentList "--version" -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Windows 成品自检失败" }
& "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe" packaging\HLibrary.iss
```

安装包输出到 `build-output/installer`。

## 发布验收

- 在 Windows 10 和 Windows 11 分别验证安装、覆盖升级、托盘、彻底退出与卸载数据选择。
- 使用中文和日文路径、前导零编号、长文件名、GIF、损坏/加密/半复制 ZIP。
- 验证新增、删除、外部改名、同名替换、上传覆盖失败回滚、跨盘迁移中断和备份恢复。
- 在真实 iPhone Safari 与 Android Chrome 上验证扫码配对、再次直连、筛选、编辑、上传、两种阅读模式、断网会话缓存和凭证撤销。
- Windows 休眠跨过凌晨 2 点后验证自动备份补做；确认自动备份始终不超过 5 份。
