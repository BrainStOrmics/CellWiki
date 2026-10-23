# CellWiki 部署指南

CellWiki 提供三种受支持的部署方式：

| 场景 | 平台 | 说明 |
| --- | --- | --- |
| 桌面端 | Windows | Tauri + NSIS，使用图形界面 |
| TUI | Linux | 终端客户端，可从源码部署到注释接口 |
| TUI | Windows | 终端客户端，与 Linux 共用同一套运行时 |

当前部署分支为 `main`，该分支提供与新版 `schema.md` 配套的完整实现。

## Windows 桌面端

桌面端只提供 Windows 版本，不提供 Linux 桌面端。当前没有公开下载页，需要从源码构建
NSIS 安装包。

1. **准备构建环境。** 需要 Windows 10/11、Git、[uv](https://docs.astral.sh/uv/)、
   Python 3.12、Node.js 22+、Rust stable 和 Tauri 的 Windows 构建依赖。

2. **取得 `main` 分支。**

   ```powershell
   git clone -b main https://github.com/BrainStOrmics/CellWiki.git
   Set-Location .\CellWiki
   ```

3. **构建安装包。**

   ```powershell
   uv sync --extra desktop
   Set-Location frontend
   npm ci
   Set-Location ..
   uv run python scripts/build_sidecar.py
   uv run python scripts/smoke_packaged_sidecar.py
   Set-Location frontend
   npm run desktop:build -- --bundles nsis
   ```

   产物位于 `frontend/src-tauri/target/release/bundle/nsis/`，文件名形如
   `Agentic CellWiki_<版本>_x64-setup.exe`。安装包尚未签名，Windows 可能显示
   SmartScreen 警告。

4. **安装并启动。** 双击安装包按向导完成当前用户安装，从开始菜单启动
   Agentic CellWiki。

5. **选择知识库目录。** 打开左下角齿轮「设置」→「工作区」→「选择文件夹…」，
   选中目录后点击「切换并使用」，并按提示重启应用。目录会被初始化成 git 仓库，
   包含 `wiki/`、`raw/` 和根级 Markdown 文件。

6. **复制页面契约。** 把仓库根目录的 [`schema.md`](schema.md) 放到知识库根目录：

   ```powershell
   Copy-Item <仓库路径>\schema.md D:\KB\my-kb\schema.md
   ```

   `schema.md` 归用户所有，Agent 只能读取。缺少它时，新页面无法通过 schema 门禁。

7. **配置模型。** 在「设置」→「模型服务」→「新建供应商」中填写 Base URL、
   API 协议、模型名和 API Key，保存后设为默认，再用「测试连接」确认连通。

8. **投料并生成 Wiki。** 在右侧「CewiPilot」面板提问，或上传 pdf/md/txt。
   附件经用户确认后晋升到 `raw/<source_id>/`，Agent 随后按 `schema.md` 读取来源
   并生成页面。

9. **审批 diff。** 在左侧「资源管理器」底部的「待审 Diff」中逐条查看补丁，
   选择接受或拒绝。接受后系统重建 `overview.md`/`statistics.md`，并追加
   `log.md`/`audit_report.md`。

## Linux TUI

以下命令默认源码目录是 `~/CellWiki`，知识库目录是 `~/kb/my-kb`。如果改用其他路径，
后续命令中的两个路径要同步替换。

1. **安装工具链。** 下面是 Debian/Ubuntu 示例：

   ```bash
   sudo apt update
   sudo apt install -y git curl openssl poppler-utils
   # 发行版仓库低于 Node.js 22 时，使用 NodeSource 安装 22.x
   curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
   sudo apt install -y nodejs
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

   重开终端后检查版本：

   ```bash
   uv --version
   git --version
   node --version    # 需要 >= 22
   ```

   如果发行版已经提供 Node.js 22+，可跳过 NodeSource 两行；其他发行版可用 nvm
   或 nodejs.org 安装。`poppler-utils` 用于把 PDF 转成可读文本。

2. **取得 `main` 分支。**

   ```bash
   cd "$HOME"
   git clone -b main https://github.com/BrainStOrmics/CellWiki.git
   cd "$HOME/CellWiki"
   ```

3. **安装 CellWiki CLI 与 TUI。**

   ```bash
   uv python install 3.12
   uv tool install "$HOME/CellWiki"
   cd "$HOME/CellWiki/terminal"
   npm ci
   npm run build
   npm link
   cd "$HOME"
   cellwiki --help
   cellwiki-tui --version
   ```

   `cellwiki` 不在 PATH 时，执行 `uv tool update-shell` 后重开终端。若 `npm link`
   报权限错误，改用用户级 npm 前缀：

   ```bash
   npm config set prefix "$HOME/.npm-global"
   export PATH="$HOME/.npm-global/bin:$PATH"
   cd "$HOME/CellWiki/terminal"
   npm link
   ```

   如果希望重开终端后仍能找到 `cellwiki-tui`，把上面的 `export PATH=...`
   写入 `~/.bashrc`。

4. **建立知识库并复制页面契约。** `schema.md` 由用户自己放入知识库，仓库只提供模板：

   ```bash
   mkdir -p "$HOME/kb/my-kb"
   cp "$HOME/CellWiki/schema.md" "$HOME/kb/my-kb/schema.md"
   ```

   `schema.md` 归用户所有，Agent 只读。缺少它时，新页面无法通过 schema 门禁。

5. **配置模型。** TUI 没有供应商设置界面，配置写在知识库根目录的 `.env`：

   ```bash
   cd "$HOME/kb/my-kb"
   cat > .env <<'EOF'
   OPENAI_API_KEY=...
   OPENAI_BASE_URL=https://your-provider/v1
   OPENAI_MODEL=your-model-id
   OPENAI_API_PROTOCOL=chat_completions
   EOF
   chmod 600 .env
   ```

   协议可取 `chat_completions`、`responses` 或 `anthropic`。首次部署可直接创建
   `.env`；已有 `.env` 时只修改对应键，不要覆盖其他配置。桌面端保存的模型配置
   不会带过来。

6. **启动 TUI。**

   ```bash
   cd "$HOME/kb/my-kb"
   cellwiki
   ```

   首次启动会自动创建 `wiki/`、`raw/`、根级 Markdown、`.gitignore` 并初始化 git；
   daemon 缺失时也会自动拉起。进入后可直接提问，`/model` 切换模型，`/resume`
   恢复历史会话，`/quit` 退出但保留后台 daemon。

7. **放入来源并产出 Wiki。** TUI 没有附件上传，需要在另一个终端把原文放进
   `raw/<source_id>/`：

   ```bash
   mkdir -p "$HOME/kb/my-kb/raw/paper1"
   cp "$HOME/papers/paper1.pdf" "$HOME/kb/my-kb/raw/paper1/article.pdf"
   pdftotext "$HOME/papers/paper1.pdf" \
     "$HOME/kb/my-kb/raw/paper1/article.extracted.txt"
   ```

   纯文本来源可以直接放入目录，不必生成 `.extracted.txt`。回到 TUI 输入：

   ```text
   读取 raw/paper1 和 schema.md，按模板生成 Wiki 页面
   ```

   Agent 完成写入后会先跑 schema lint，再提交待确认 diff：

   - `1` 接受，页面进入 `wiki/`。
   - `2` 拒绝本次改动。
   - `3` 查看完整 diff。
   - `Esc` 稍后处理。

   接受后系统重建 `overview.md`/`statistics.md`，并追加
   `log.md`/`audit_report.md`。

8. **开启注释接口。** 先在 TUI 执行 `/quit`，然后生成独立令牌并重启 daemon：

   ```bash
   TOKEN="$(openssl rand -hex 32)"
   printf '\nCELLWIKI_ANNOTATION_API_TOKEN=%s\n' "$TOKEN" \
     >> "$HOME/kb/my-kb/.env"
   chmod 600 "$HOME/kb/my-kb/.env"
   cellwiki daemon restart --workspace "$HOME/kb/my-kb"
   cellwiki daemon status --workspace "$HOME/kb/my-kb"
   ```

   `status` 输出 JSON 中的 `port` 是监听端口。令牌只用于注释接口，不能复用模型
   API Key 或桌面端 bearer token。

9. **自检接口。**

   ```bash
   cd "$HOME/CellWiki"
   export CELLWIKI_ANNOTATION_API_TOKEN="$(
     sed -n 's/^CELLWIKI_ANNOTATION_API_TOKEN=//p' "$HOME/kb/my-kb/.env" | tail -n 1
   )"
   python3 scripts/annotation_smoke.py --workspace "$HOME/kb/my-kb"
   ```

   退出码为 0 且输出 PASS 清单，才表示 daemon、令牌、知识库和接口合同均已接通。

10. **供下游注释 Agent 调用。** 接口只监听本机 `127.0.0.1`，下游 Agent 必须与
    CellWiki 在同一主机运行。先读取端口并导出令牌：

    ```bash
    cd "$HOME/CellWiki"
    export CELLWIKI_ANNOTATION_API_TOKEN="$(
      sed -n 's/^CELLWIKI_ANNOTATION_API_TOKEN=//p' "$HOME/kb/my-kb/.env" | tail -n 1
    )"
    cellwiki daemon status --workspace "$HOME/kb/my-kb"
    ```

    可直接发 HTTP 请求：

    ```bash
    PORT="<daemon status 输出里的 port>"
    curl -sS "http://127.0.0.1:${PORT}/api/v1/annotation-support" \
      -H "Authorization: Bearer ${CELLWIKI_ANNOTATION_API_TOKEN}" \
      -H "Content-Type: application/json" \
      -d '{
        "request_id": "req-001",
        "species": "Homo sapiens",
        "tissue": "colorectal_tumor",
        "disease": null,
        "cluster": {"id": "c1"},
        "top_markers": ["GPR183", "CD4", "IL7R"],
        "low_or_absent_markers": ["FOXP3"]
      }'
    ```

    也可以使用仓库自带客户端：

    ```bash
    python3 scripts/annotation_client.py \
      --workspace "$HOME/kb/my-kb" \
      --species "Homo sapiens" \
      --tissue colorectal_tumor \
      --markers GPR183,CD4,IL7R \
      --absent FOXP3 \
      --parent-cell-type cd4_pos_t_cell
    ```

    接口只读已提交且已审批的知识；有活动 run 或未审批 diff 时返回
    `503 KNOWLEDGE_BUSY`。完整请求、响应和错误合同见
    [注释证据接口接入说明](ANNOTATION_API.md)。

## Windows TUI

Windows 使用同一套运行时和接口，只替换安装命令与路径。前置条件为 Windows 10/11、
Python 3.12、[uv](https://docs.astral.sh/uv/)、Node.js 22+ 和 Git。

1. **安装 CLI 与 TUI。**

   ```powershell
   uv python install 3.12
   uv tool install D:\path\to\CellWiki
   Set-Location D:\path\to\CellWiki\terminal
   npm ci
   npm run build
   npm link
   ```

   若 `cellwiki` 不在 PATH，执行 `uv tool update-shell` 后重开终端。

2. **建立知识库并复制 `schema.md`。**

   ```powershell
   New-Item -ItemType Directory -Force D:\KB\my-kb | Out-Null
   Copy-Item D:\path\to\CellWiki\schema.md D:\KB\my-kb\schema.md
   ```

3. **配置模型。** 在 `D:\KB\my-kb\.env` 写入四个 `OPENAI_*` 键：

   ```dotenv
   OPENAI_API_KEY=...
   OPENAI_BASE_URL=https://your-provider/v1
   OPENAI_MODEL=your-model-id
   OPENAI_API_PROTOCOL=chat_completions
   ```

   该文件已被工作区 `.gitignore` 排除，不会进入 git。

4. **启动 TUI。**

   ```powershell
   Set-Location D:\KB\my-kb
   cellwiki
   ```

   Windows 经典控制台显示异常时，用 `cellwiki-tui --classic` 或设置
   `CELLWIKI_TUI_CLASSIC=1`。

5. **放入来源并产出 Wiki。** 把原文放入 `D:\KB\my-kb\raw\<source_id>\`。PDF
   需要同时准备可读文本，纯文本或 Markdown 可以直接使用。然后在 TUI 输入：

   ```text
   读取 raw/paper1 和 schema.md，按模板生成 Wiki 页面
   ```

   审批时使用 `1` 接受、`2` 拒绝、`3` 查看 diff、`Esc` 稍后。

6. **开放注释接口。** 在知识库 `.env` 增加独立令牌：

   ```dotenv
   CELLWIKI_ANNOTATION_API_TOKEN=<长随机串>
   ```

   重启 daemon 并读取端口：

   ```powershell
   cellwiki daemon restart --workspace D:\KB\my-kb
   cellwiki daemon status --workspace D:\KB\my-kb
   ```

7. **自检并供下游调用。**

   ```powershell
   $env:CELLWIKI_ANNOTATION_API_TOKEN = "<同一令牌>"
   python scripts\annotation_smoke.py --workspace D:\KB\my-kb
   ```

   下游 Agent 可在同一主机通过
   `POST http://127.0.0.1:<port>/api/v1/annotation-support` 调用，完整 PowerShell
   示例见 [注释证据接口接入说明](ANNOTATION_API.md)。

## 相关文档

- [项目 README](README.md)
- [TUI 命令与按键](terminal/README.md)
- [注释证据接口接入说明](ANNOTATION_API.md)
