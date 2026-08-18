# HManガ

HManガ是一个运行在 Windows 上的本地漫画与插画管理软件。Windows 主程序保存和管理作品，已配对手机可在同一 Wi-Fi 下通过浏览器搜索、分类和阅读。

## 项目文档

- [最终需求](REQUIREMENTS.md)：功能、规则和验收要求。
- [技术架构](ARCHITECTURE.md)：技术栈、数据模型、进程结构、安全和关键事务。
- [页面与文字线框](UI_SPEC.md)：Windows 与手机页面结构和交互。
- [开发实施计划](IMPLEMENTATION_PLAN.md)：阶段拆分、交付物和验收条件。

## 当前状态

HManガ 已实现 Windows 本地管理与同一 Wi-Fi 手机浏览器访问的完整主流程：

- PySide6 Windows/Ubuntu 桌面窗口与系统托盘。
- FastAPI 局域网鉴权、媒体、上传与实时通知接口。
- SQLite/SQLAlchemy 完整管理资料与阅读进度数据库。
- React/TypeScript 响应式手机管理与阅读页面。
- Python 测试、Windows CI、PyInstaller 和 Inno Setup 配置。
- 首次选择作品目录，并自动建立 `插画` 和 `备份` 子目录。
- 扫描有效 ZIP 漫画与图片，记录新增、丢失、重命名和同名替换。
- 软件运行时监控目录变化，并显示作品和汇总通知。
- 标题搜索、Tag/分组、星级、筛选、排序、50 条分页、封面和详情编辑。
- 连续/单页漫画阅读、按需解码、缩放拖动、共享进度和 5 秒恢复入口。
- Windows 拖放/批量上传、同名覆盖确认与失败回滚。
- 手机二维码/配对码、持久凭证、设备撤销、响应式页面和实时通知。
- 自动/手动备份、恢复前保护、1GB 默认缓存治理和作品目录迁移。

## Ubuntu 开发运行

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/hmanga
```

前端需要 Node.js 22：

```bash
cd frontend
npm install
npm run build
```

详细操作见 [用户说明](USER_GUIDE.md)，开发与 Windows 构建见 [开发说明](DEVELOPMENT.md)。
