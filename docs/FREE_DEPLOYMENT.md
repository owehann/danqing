# Danqing (丹青) 零支付风险（物理级 \$0.00 锁死）公网部署指南

为**彻底隔离一切按量计费与超支扣费风险**，本项目已移除所有按量计费云平台（如 AWS / Google Cloud）脚本，仅提供**无需绑定信用卡、物理上不可能产生任何账单**的两种零成本开放方式：

---

## 方式一：24 小时云端托管（Render Free Tier · 免绑信用卡 · \$0.00 锁死）

仓库根目录内置了 [`render.yaml`](../render.yaml) 免费蓝图（`plan: free` + `DANQING_LOW_MEMORY=1` 低内存模式，启动仅占 `~115 MB` 内存，完全适配 `512 MB` 免费容器）：

1. 在浏览器使用 GitHub 账号一键登录 [Render Dashboard](https://dashboard.render.com/)（**全程无需填写信用卡**）。
2. 打开一键部署蓝图链接：
   - `https://render.com/deploy?repo=https://github.com/owehann/danqing`
3. 确认页面显示 **`Free ($0/month)`**，点击 **Apply / Deploy** 即可获得永久 HTTPS 域名（如 `https://danqing.onrender.com`）。
   - 免费实例每月含 `750 小时`（足够单实例 7×24 小时覆盖整月 `720–744 小时`）；无人访问 15 分钟自动休眠，有人打开链接时约 20 秒自动唤醒，**超额也只会暂停直到下月重置，绝无任何扣费可能**。

---

## 方式二：本机秒级加密公网隧道（Cloudflare Quick Tunnel · 免注册 · \$0.00）

当需要在组会、审稿展示或大文件极速响应场景下立即分享：

```bash
./scripts/share_public.sh
```

- 自动下载官方 `cloudflared` 二进制并分配 `https://*.trycloudflare.com` 加密公网地址（手机与电脑均可直接打开）。
- 若仅在同一实验室或校园 Wi-Fi 内分享，运行 `./scripts/share_public.sh --lan` 即可开启局域网直连。

---

## 多用户隐私隔离保证（Zero-Retention RAM Sandbox）

- **零落盘（RAM-Only）**：所有上传的 PDF/SVG、重着色缓存与导出压缩包 100% 驻留于进程内存，关闭标签页、点击删除或会话满 `10 分钟` 即触发内存覆写回收（`gc.collect()`）。
- **密码学级访客隔离**：服务端每次启动生成随机 256-bit 密钥签发 `HttpOnly + SameSite=Lax` 访客凭证 `dq_sid`，配合 128-bit `fig_<32hex>` 随机句柄；访客 A 与访客 B 之间物理不可枚举、不可互读（跨访客请求一律返回 `404`），连内置示例图的调色状态也按访客独立克隆。
