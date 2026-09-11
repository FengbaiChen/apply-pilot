# ApplyPilot 当前设计

ApplyPilot 是单用户本地服务：FastAPI 负责会话 API 和控制台，Playwright 负责一个持久化的可见 Chromium，Workday runner 负责五步向导。

## 运行流程

`POST /applications` 只接受 `platform: workday`。服务验证 profile 中恰好五条完整经历，然后打开职位 URL。Workday 登录、注册、MFA 和 CAPTCHA 会暂停流程。每个步骤扫描实时 DOM，按 profile、保存答案、LLM 的顺序解析答案，填写后重新扫描并校验，再点击安全的 Save and Continue。进入 Review 后状态变为 `READY_FOR_REVIEW`，不会调用任何提交动作。

## 五步规则

- My Information：来源固定为 LinkedIn Jobs；previous employer 固定 No；个人、地址、电话来自 profile；电话控件使用独立国家代码和 national digits。
- My Experience：创建并填写五条工作记录；冲突时暂停；填写一条 Ann Arbor 教育、简历、GitHub 和 LinkedIn；Skills 和其他可选空字段跳过。
- Application Questions：profile 事实优先；历史答案按标准化问题/类型/选项匹配；未知必填题先调用 LLM，dropdown 必须精确命中页面选项，失败则暂停。
- Voluntary Disclosures：只使用显式 profile 值。明确的 Terms/Privacy 必填同意框可自动勾选，其他 consent 不自动操作。
- Review：本地审计显示字段、答案、来源和原因；批准接口可把编辑后的值写入网页并保存长期答案，但不会 Submit。

## 数据边界

`config/profile.yaml` 是唯一长期资料来源，包含个人信息、电话、授权事实、单条教育、五条工作经历、自愿披露、链接和 `saved_answers`。简历只上传，不解析。SQLite 只记录会话和审计状态。LLM 不接收密码或简历路径；生成答案必须在 Review 中标记，批准后才写入 profile。

## API

- `POST /applications`：启动 Workday 会话。
- `GET /applications/{id}`：读取状态和待处理问题。
- `POST /applications/{id}/answers`：提交当前暂停页的人工答案。
- `POST /applications/{id}/resume`：登录/MFA/手工处理后继续。
- `GET /applications/{id}/review`：读取审计。
- `POST /applications/{id}/review/approve`：应用审核编辑并保存批准答案。
- `POST /applications/{id}/stop`：关闭浏览器和会话。

应用只允许一个活跃浏览器，并且要求单 Uvicorn worker。参考目录中的其他仓库不参与运行时。
