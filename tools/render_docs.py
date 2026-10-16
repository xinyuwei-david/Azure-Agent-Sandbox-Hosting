#!/usr/bin/env python3
"""Fill the generated blocks and inline values of README.md, README_CN.md, VALIDATION.md and VALIDATION_CN.md.

    python tools/render_docs.py           # rewrite the four pages in place
    python tools/render_docs.py --check   # fail if any page differs from a fresh render

Two kinds of generated content, both rebuilt from evidence/runs/ (hash-checked) and
evidence/measurements.json (must equal a fresh build):

    <!-- BEGIN GENERATED: name -->...<!-- END GENERATED: name -->   tables and verbatim inputs
    <!--v:metric.field-->value<!--/v-->                             one number inside prose

Hand-written prose around them is left untouched. An unknown block or field fails the render.
The results tables follow the canonical run_order in evidence/claims.json.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_measurements as bm  # noqa: E402

ROOT = bm.ROOT
PAGES = {"README.md": "en", "README_CN.md": "zh", "VALIDATION.md": "en", "VALIDATION_CN.md": "zh"}
BLOCK_RE = re.compile(r"(<!-- BEGIN GENERATED: ([a-z0-9-]+) -->\n)(.*?)(<!-- END GENERATED: \2 -->)", re.S)
VALUE_RE = re.compile(r"<!--v:([a-z0-9_.]+)-->(.*?)<!--/v-->")


class RenderError(RuntimeError):
    pass


def num(v, places: int = 2) -> str:
    """Seconds keep two decimals (three for sub-100ms values; trailing zeros dropped, one kept); prices pass places=3."""
    if isinstance(v, bool):
        raise RenderError(f"boolean where a number was expected: {v}")
    if isinstance(v, int):
        return str(v)
    if float(v).is_integer() and abs(v) >= 100:
        return str(int(v))
    if places == 2 and 0 < abs(float(v)) < 0.1:
        places = 3
    s = f"{v:.{places}f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


def rng(rec: dict) -> str:
    return f"{num(rec['min'])}–{num(rec['max'])}"


class Ctx:
    def __init__(self, metrics: dict, runs: dict, lang: str):
        self.m, self.runs, self.lang = metrics, runs, lang

    def t(self, en: str, zh: str) -> str:
        return en if self.lang == "en" else zh

    def med(self, key: str) -> str:
        r = self.m[key]
        if "median" not in r:
            return self.vals(key)
        return self.t(f"{num(r['median'])} s median ({rng(r)}; n={r['n']})",
                      f"中位数 {num(r['median'])} s（{rng(r)}；n={r['n']}）")

    def vals(self, key: str) -> str:
        r = self.m[key]
        joined = ", ".join(num(v) for v in r["values"])
        return f"{joined} s (n={r['n']})" if self.lang == "en" else f"{joined} s（n={r['n']}）"

    def one(self, key: str) -> str:
        r = self.m[key]
        return self.t(f"{num(r['value'])} s (n=1)", f"{num(r['value'])} s（n=1）")

    def rng_n(self, key: str) -> str:
        r = self.m[key]
        return self.t(f"{rng(r)} s (n={r['n']})", f"{rng(r)} s（n={r['n']}）")


def table(head: list[str], rows: list[list[str]], align: list[str] | None = None) -> str:
    align = align or ["---"] * len(head)
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join(align) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def quote(lines: list[str]) -> str:
    return "\n".join(f"> {ln}" for ln in lines) + "\n"


# --- README blocks --------------------------------------------------------------------------------

def comparison_details(c: Ctx) -> tuple[list[str], list[list[str]], str]:
    m = c.m
    k = m["b.sess.state_kept"]
    claims = json.loads((ROOT / "evidence" / "claims.json").read_text(encoding="utf-8"))
    head = [c.t("Observed or documented", "实测或文档项"), "A · ACA Sandboxes",
            c.t("B · Foundry hosted agent", "B · Foundry hosted agent"),
            "C · AKS + agent-sandbox", "D · BYO-AKS", "E · E2B on Azure VM"]
    rows = [
        [c.t("**Cold start = sum of**", "**冷启动 = 哪几段相加**"),
         c.t("sandbox create → Running + first answer (timed inside the sandbox)",
             "沙箱创建 → Running + 第一个回答（沙箱内计时）"),
         c.t("create session → `active` + first answer (two client requests)",
             "创建会话 → `active` + 第一个回答（客户端发两次请求）"),
         c.t("`kubectl apply` → Sandbox Ready (includes the Blob PVC mount) + first answer (at the LoadBalancer)",
             "`kubectl apply` → Sandbox Ready（含挂 Blob PVC）+ 第一个回答（LoadBalancer 处计时）"),
         c.t("session pod created → Ready + pod Ready → first answer (endpoint, session and agent path)",
             "会话 pod 创建 → Ready + pod Ready 后到第一个回答（端点、会话和 agent 链路）"),
         c.t("E2B sandbox create → Running + first answer (Prompt Agent turn that calls the sandbox tool)",
             "E2B 沙箱创建 → Running + 第一个回答（调用沙箱工具的 Prompt Agent 轮次）")],
        [c.t("**Pure cold start, no external volume (total)**", "**纯冷启动总计（不挂外部卷）**"),
         c.t(f"**{num(m['a.cold_no_volume']['value'])} s** derived ({num(m['a.attr.image']['median'])} s + "
             f"{num(m['a.first_answer']['median'])} s, medians of separate runs)",
             f"**{num(m['a.cold_no_volume']['value'])} s** 合成值（{num(m['a.attr.image']['median'])} s + "
             f"{num(m['a.first_answer']['median'])} s，取自不同实测的中位数）"),
         c.t(f"**{num(m['b.sess.cold']['median'])} s** median ({rng(m['b.sess.cold'])}; n={m['b.sess.cold']['n']}), "
             f"added per run; one request that auto-creates the session on the first `/responses`: "
             f"{num(m['b.cold_gateway']['value'])} s (gateway model route) / {num(m['b.cold_direct']['value'])} s "
             "(direct), n=1 each",
             f"**{num(m['b.sess.cold']['median'])} s** 中位数（{rng(m['b.sess.cold'])}；n={m['b.sess.cold']['n']}），"
             f"每次实测相加；首次 `/responses` 自动建会话、一次请求完成：{num(m['b.cold_gateway']['value'])} s"
             f"（gateway 模型路由）/ {num(m['b.cold_direct']['value'])} s（direct），各 n=1"),
         c.t("not measured: C keeps state across suspend only through the Blob PVC, so every measured cold start mounted it",
             "未测：C 只能靠 Blob PVC 跨挂起保状态，所以实测的冷启动都挂了卷"),
         c.t(f"**{num(m['d.cold']['median'])} s** median ({rng(m['d.cold'])}; n={m['d.cold']['n']}), "
             "one request via the Foundry endpoint",
             f"**{num(m['d.cold']['median'])} s** 中位数（{rng(m['d.cold'])}；n={m['d.cold']['n']}），经 Foundry 端点一次请求"),
         c.t(f"**{num(m['e.cold']['median'])} s** median ({rng(m['e.cold'])}; n={m['e.cold']['n']}), added per run "
             f"(A protocol); {c.med('e.d_cold')} in one request (D protocol)",
             f"**{num(m['e.cold']['median'])} s** 中位数（{rng(m['e.cold'])}；n={m['e.cold']['n']}），每次实测相加"
             f"（A 口径）；一次请求 {c.med('e.d_cold')}（D 口径）")],
        [c.t("└ part 1: sandbox, session or pod ready", "└ 子项 1：沙箱、会话或 pod 就绪"),
         c.t(f"{c.med('a.attr.image')} (image only); with VNet {rng(m['a.attr.vnet'])} s (n={m['a.attr.vnet']['n']}), "
             f"port {rng(m['a.attr.port'])} s (n={m['a.attr.port']['n']})",
             f"{c.med('a.attr.image')}（仅镜像）；加 VNet {rng(m['a.attr.vnet'])} s（n={m['a.attr.vnet']['n']}），"
             f"加端口 {rng(m['a.attr.port'])} s（n={m['a.attr.port']['n']}）"),
         c.t(f"{c.med('b.sess.create')}, `POST .../endpoint/sessions` → `active`",
             f"{c.med('b.sess.create')}，`POST .../endpoint/sessions` → `active`"),
         c.t("not measured without the PVC", "未测（不挂 PVC）"),
         c.t(f"{rng(m['d.pod_ready'])} s (n={m['d.pod_ready']['n']}) with the image cached; "
             f"{num(m['d.pod_ready_fresh']['min'])} s on a fresh node (n={m['d.pod_ready_fresh']['n']})",
             f"镜像已缓存 {rng(m['d.pod_ready'])} s（n={m['d.pod_ready']['n']}）；新节点 "
             f"{num(m['d.pod_ready_fresh']['min'])} s（n={m['d.pod_ready_fresh']['n']}）"),
         c.t(f"{c.med('e.create')} in the agent runs; {c.rng_n('e.bench20.create')} in the on-host microbenchmark",
             f"agent 实测中 {c.med('e.create')}；本机微基准 {c.rng_n('e.bench20.create')}")],
        [c.t("└ part 2: ready → first answer", "└ 子项 2：就绪后 → 第一个回答"),
         c.t(f"{c.med('a.first_answer')}, timed inside the sandbox",
             f"{c.med('a.first_answer')}，沙箱内计时"),
         c.t(f"{c.med('b.sess.first')} on the active session; the service recorded "
             f"{rng(m['b.sess.first_server'])} s of it as generation",
             f"已就绪会话上 {c.med('b.sess.first')}；其中服务端记录的生成时间 {rng(m['b.sess.first_server'])} s"),
         c.t(f"{num(m['c.first']['value'])} s (n=1), at the LoadBalancer",
             f"{num(m['c.first']['value'])} s（n=1），在 LoadBalancer 处计时"),
         c.t(f"{c.med('d.first_after_ready')} after pod Ready (agent turn {rng(m['d.agent_turn'])} s)",
             f"pod Ready 后 {c.med('d.first_after_ready')}（agent 轮次 {rng(m['d.agent_turn'])} s）"),
         c.t(f"{c.med('e.first_answer')} (A protocol); {c.med('e.d_agent_turn')} (D protocol)",
             f"{c.med('e.first_answer')}（A 口径）；{c.med('e.d_agent_turn')}（D 口径）")],
        [c.t("**Cold start with a private Blob volume (total)**", "**带私有 Blob 卷的冷启动总计**"),
         c.t(f"**{num(m['a.cold']['median'])} s** median ({rng(m['a.cold'])}; n={m['a.cold']['n']}); "
             "SDK create + answer inside sandbox",
             f"**{num(m['a.cold']['median'])} s** 中位数（{rng(m['a.cold'])}；n={m['a.cold']['n']}）；SDK 创建 + 沙箱内回答"),
         c.t("no external volume (the platform restores `$HOME` and `/files`)",
             "不挂外部卷（平台恢复 `$HOME` 和 `/files`）"),
         c.t(f"**{num(m['c.cold']['value'])} s** (n=1; apply → Ready {num(m['c.apply_ready']['value'])} s + answer "
             f"{num(m['c.first']['value'])} s)",
             f"**{num(m['c.cold']['value'])} s**（n=1；apply → Ready {num(m['c.apply_ready']['value'])} s + 回答 "
             f"{num(m['c.first']['value'])} s）"),
         c.t("no external volume in the session pod", "会话 pod 未挂外部卷"),
         c.t("no external volume (templates and snapshots stay on the host VM's OS disk)",
             "不挂外部卷（模板和快照存在宿主 VM 的系统盘上）")],
        [c.t("└ volume overhead", "└ 子项：挂卷附加耗时"),
         c.t(f"+{num(m['a.blob_mount_overhead']['value'])} s median vs image only (create → Running {c.med('a.create')}); "
             "Memory snapshots need no volume",
             f"比仅镜像多 +{num(m['a.blob_mount_overhead']['value'])} s 中位数（create → Running {c.med('a.create')}）；"
             "Memory 快照无需挂卷"),
         c.t("none", "无"),
         c.t(f"not separable: no run without the PVC (apply → Ready {num(m['c.apply_ready']['value'])} s includes it, n=1)",
             f"无法拆出：没有不挂 PVC 的实测（apply → Ready {num(m['c.apply_ready']['value'])} s 已包含挂卷，n=1）"),
         c.t("none", "无"),
         c.t("none", "无")],
        [c.t("**Follow-up turn, same session**", "**同一会话的后续回答**"),
         c.med("a.warm"),
         c.t(f"{c.vals('b.warm_gateway')} (`b-2026-09-27`, gateway model route); "
             f"{c.med('b.sess.warm')} (`b-2026-10-15-sessions`, direct model route)",
             f"{c.vals('b.warm_gateway')}（`b-2026-09-27`，gateway 模型路由）；"
             f"{c.med('b.sess.warm')}（`b-2026-10-15-sessions`，direct 模型路由）"),
         c.one("c.warm"), c.med("d.warm"),
         c.t(f"{c.med('e.warm')} (A protocol); {c.med('e.d_warm')} (D protocol); "
             f"on-host sandbox command {c.rng_n('e.bench20.warm_cmd')}",
             f"{c.med('e.warm')}（A 口径）；{c.med('e.d_warm')}（D 口径）；"
             f"本机沙箱内命令 {c.rng_n('e.bench20.warm_cmd')}")],
        [c.t("**Suspend / pause and wake until ready**", "**挂起 / 暂停与恢复就绪耗时**"),
         c.t(f"stop {c.med('a.stop')}; resume → Running {rng(m['a.attr.resume_small'])} s "
             f"(n={m['a.attr.resume_small']['n']}, no volume), {c.med('a.resume')} (with Blob volume)",
             f"停止 {c.med('a.stop')}；恢复 → Running 不挂卷 {rng(m['a.attr.resume_small'])} s"
             f"（n={m['a.attr.resume_small']['n']}），带 Blob 卷 {c.med('a.resume')}"),
         c.t(f"`:stop` → idle {c.med('b.sess.stop')}; compute released, `$HOME` kept, no memory snapshot; "
             "wakes on the next request (next row)",
             f"`:stop` → idle {c.med('b.sess.stop')}；释放算力、保留 `$HOME`，无内存快照；下一次请求时唤醒（见下一行）"),
         c.t(f"suspend → pod gone {num(m['c.suspend']['value'])} s (n=1); resume → Ready "
             f"{num(m['c.resume_ready']['value'])} s, LoadBalancer healthy {num(m['c.resume_lb']['value'])} s (n=1)",
             f"挂起 → pod 消失 {num(m['c.suspend']['value'])} s（n=1）；恢复 → Ready "
             f"{num(m['c.resume_ready']['value'])} s，LoadBalancer 健康 {num(m['c.resume_lb']['value'])} s（n=1）"),
         claims["paths"]["D"][f"memory_suspend_{c.lang}"],
         c.t(f"pause {c.med('e.stop')} (on host {c.rng_n('e.bench20.pause')}); "
             f"resume → Running {c.med('e.resume')} (on host {c.rng_n('e.bench20.resume')})",
             f"暂停 {c.med('e.stop')}（本机 {c.rng_n('e.bench20.pause')}）；"
             f"恢复 → Running {c.med('e.resume')}（本机 {c.rng_n('e.bench20.resume')}）")],
        [c.t("**Resume request → first answer (stop excluded)**", "**发起恢复 → 第一个回答（不含停止）**"),
         c.t(c.med("a.recover") + f"; separately reported resume-only median {num(m['a.resume']['median'])} s",
             c.med("a.recover") + f"；恢复本身另行统计的中位数 {num(m['a.resume']['median'])} s"),
         c.t(f"{c.med('b.sess.resume')}: the next turn on the stopped session gets new compute with `$HOME` restored; "
             f"file written before the stop read back {k['files']}/{k['n']}, question count kept growing "
             f"{k['conversation']}/{k['n']}",
             f"{c.med('b.sess.resume')}：停止后同一会话的下一轮请求分到新算力并恢复 `$HOME`；"
             f"停止前写入的文件读回 {k['files']}/{k['n']}，问题计数持续增长 {k['conversation']}/{k['n']}"),
         c.t(f"{num(m['c.resume_answer']['value'])} s (n=1; Ready {num(m['c.resume_ready']['value'])} s, "
             f"LoadBalancer healthy {num(m['c.resume_lb']['value'])} s)",
             f"{num(m['c.resume_answer']['value'])} s（n=1；Ready {num(m['c.resume_ready']['value'])} s，"
             f"LoadBalancer 健康 {num(m['c.resume_lb']['value'])} s）"),
         claims["paths"]["D"][f"memory_suspend_{c.lang}"],
         c.t(c.med("e.recover") + f"; separately reported resume-only median {num(m['e.resume']['median'])} s",
             c.med("e.recover") + f"；恢复本身另行统计的中位数 {num(m['e.resume']['median'])} s")],
        [c.t("**Pod or sandbox lost → ready again**", "**pod 或沙箱丢失 → 重新就绪**"),
         c.t("not exercisable: no API injects host loss, and deleting a sandbox ends it",
             "无法从外部制造：没有注入宿主机故障的接口，删除沙箱即结束会话"),
         c.t("not exercisable: no API kills only a session's sandbox; explicit stop and resume are above",
             "无法从外部制造：没有只杀掉会话沙箱的接口；显式停止与恢复见上方"),
         c.t(c.one("c.pod_lost") + "; same Sandbox state restored",
             c.one("c.pod_lost") + "；同一 Sandbox 的状态已恢复"),
         c.t(c.one("d.pod_lost") + "; deleted session continuity not tested",
             c.one("d.pod_lost") + "；未测试被删会话的连续性"),
         c.t(c.one("e.pod_lost") + f"; another live session answered in {num(m['e.other_session_followup']['value'])} s",
             c.one("e.pod_lost") + f"；另一个存活会话在 {num(m['e.other_session_followup']['value'])} s 内回答")],
        [c.t("**Idle policy (official docs)**", "**空闲策略（官方说明）**"),
         *(claims["paths"][letter][f"idle_policy_{c.lang}"] for letter in ("A", "B", "C", "D", "E"))],
        [c.t("**Capacity**", "**容量**"),
         c.t("serverless; default 500 concurrent active cores (2000 standard limit, 20000 in our subscription) and 3000 requests/min ([docs](https://sandboxes.azure.com/docs/sandboxes/limits)); stopped sandboxes do not count",
             "无服务器；默认 500 并发活跃核（标准上限 2000，本订阅实查 20000）及 3000 请求/分钟（[文档](https://sandboxes.azure.com/docs/sandboxes/limits)）；已停止的沙箱不计入"),
         c.t("one VM-isolated sandbox per session, scaled per session with no replica count or warm pool to configure ([docs](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents#scaling-and-right-sizing)); up to 20 GiB disk per session (20% system-reserved) and 50 MB per uploaded file",
             "每个会话一个 VM 隔离的沙箱，按会话扩缩，没有副本数或预热池可配置（[文档](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents#scaling-and-right-sizing)）；单会话最高 20 GiB 磁盘（系统预留 20%），单个上传文件最大 50 MB"),
         c.t("your Kata node pool", "你的 Kata 节点池"),
         c.t(f"observed at most {m['d.capacity']['per_node']} per {m['d.capacity']['node_sku']} node; "
             f"{m['d.capacity']['max_sessions']} on {m['d.capacity']['n']} nodes; "
             + ", ".join(f"`{code}`" for n in (4, 8) for code in m[f'd.c{n}']['refused_codes']),
             f"单个 {m['d.capacity']['node_sku']} 节点观察到最多 {m['d.capacity']['per_node']} 个会话；"
             f"{m['d.capacity']['n']} 个节点共 {m['d.capacity']['max_sessions']} 个；"
             + "、".join(f"`{code}`" for n in (4, 8) for code in m[f'd.c{n}']['refused_codes'])),
         c.t(f"one machine per install, by design ([E2B](https://github.com/e2b-dev/runtime/blob/"
             f"588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/README.md#when-one-node-is-not-enough)); "
             f"2026-10-14 on 1 {m['e.capacity']['node_sku']} VM: 4 at once {m['e.c4']['answered']}/{m['e.c4']['n']}, "
             f"8 at once {m['e.c8']['answered']}/{m['e.c8']['n']}; 2026-10-15 on one host "
             f"{m['e.multi.one_host']['answered']}/{m['e.multi.one_host']['n']} and on two independent hosts "
             f"{m['e.multi.two_hosts']['answered']}/{m['e.multi.two_hosts']['n']}; the default hugepage pool held "
             f"{m['e.multi.idle']['max']} `base` sandboxes per host",
             f"每套安装只有一台机器，这是设计如此（[E2B](https://github.com/e2b-dev/runtime/blob/"
             f"588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/README.md#when-one-node-is-not-enough)）；"
             f"2026-10-14 在 1 台 {m['e.capacity']['node_sku']} VM 上：4 并发 {m['e.c4']['answered']}/{m['e.c4']['n']}、"
             f"8 并发 {m['e.c8']['answered']}/{m['e.c8']['n']}；2026-10-15 单台 "
             f"{m['e.multi.one_host']['answered']}/{m['e.multi.one_host']['n']}、两台独立主机 "
             f"{m['e.multi.two_hosts']['answered']}/{m['e.multi.two_hosts']['n']}；默认大页池每台最多放下 "
             f"{m['e.multi.idle']['max']} 个 `base` 沙箱")],
        [c.t("**Path setup in our run**", "**本次路径部署耗时**"),
         c.t(f"{num(m['a.setup']['value'])} s (sandbox group, VNet connection, disk image, volume, sandbox)",
             f"{num(m['a.setup']['value'])} s（sandbox group、VNet 连接、磁盘镜像、卷、沙箱）"),
         c.t(f"{num(m['b.deploy']['value'])} s (`azd deploy`; model route: gateway (APIM))",
             f"{num(m['b.deploy']['value'])} s（`azd deploy`；模型路由：gateway（APIM））"),
         c.t(f"{num(m['c.setup']['value'])} s (prepare script, private link, apply)",
             f"{num(m['c.setup']['value'])} s（准备脚本、私有链接、apply）"),
         c.t(f"{num(m['d.onboarding']['value'])} s (roles, `azd provision`, `azd deploy`; author's console, not kept)",
             f"{num(m['d.onboarding']['value'])} s（角色、`azd provision`、`azd deploy`；作者控制台记录，原始输出未保留）"),
         c.t(f"{num(m['e.setup']['value'])} s (Docker Engine {num(m['e.setup']['parts'][0])} s + "
             f"E2B Compose and base template {num(m['e.setup']['parts'][1])} s)",
             f"{num(m['e.setup']['value'])} s（Docker Engine {num(m['e.setup']['parts'][0])} s + "
             f"E2B Compose 与 base 模板 {num(m['e.setup']['parts'][1])} s）")],
    ]
    spec = c.runs["a-aca-2026-10-09/agent-runs.json"]["sandbox_spec"]
    observation = c.t(
        f"**Local configuration and observation, not official idle policy:** A used "
        f"{spec['auto_suspend_mode']} mode with a {spec['auto_suspend_seconds']} s auto-suspend setting. "
        f"D's oldest pod was still Running at least {m['d.idle']['value']} min after creation; "
        "this is pod age, not idle duration or a reclamation timeout.",
        f"**本地配置与观察，不是官网空闲策略：** A 本次使用 {spec['auto_suspend_mode']} 模式，"
        f"自动挂起设置为 {spec['auto_suspend_seconds']} s。D 最早的 pod 在创建至少 "
        f"{m['d.idle']['value']} min 后仍为 Running；这是 pod 的年龄，不是空闲时长或回收超时。")
    return head, rows, observation


# GitHub removes <wbr> and inline CSS. Soft hyphens and split code spans keep the full table wrappable.
TABLE_WORD_BREAKS = {
    "LoadBalancer": "Load|Balancer", "Sandboxes": "Sand|boxes", "concurrent": "con|current",
    "configurable": "config|urable", "configure": "con|figure", "connection": "con|nection",
    "continuity": "con|tinuity", "detection": "de|tection", "documented": "docu|mented",
    "exercisable": "exer|cisable", "exercised": "exer|cised", "generation": "gener|ation",
    "implement": "imple|ment", "inactivity": "in|activity", "independent": "inde|pendent",
    "microbenchmark": "micro|bench|mark", "persisted": "per|sisted", "recycling": "re|cycling",
    "sandboxes": "sand|boxes", "scheduled": "sched|uled", "separable": "sep|arable",
    "separately": "sep|arately", "serverless": "server|less", "shutdownTime": "shutdown|Time",
    "snapshots": "snap|shots", "subscription": "sub|scrip|tion", "templates": "tem|plates",
}


def wrap_table_cell(text: str) -> str:
    parts = re.split(r"(`[^`\n]+`|\[[^\]\n]+\]\([^)]+\))", text)
    for i, part in enumerate(parts):
        if part.startswith("`"):
            code = part[1:-1]
            if len(code) >= 10:
                pieces = re.split(r"(?<=[ _/\-])(?=.)", code)
                parts[i] = "<br>".join(f"<code>{html.escape(piece)}</code>" for piece in pieces) + "&#8203;"
        elif part.startswith("["):
            label, url = part.split("](", 1)
            parts[i] = f"[{wrap_table_cell(label[1:])}]({url}"
        else:
            part = re.sub(r"[A-Za-z]{9,}", lambda m: TABLE_WORD_BREAKS.get(m[0], m[0]).replace("|", "&shy;"), part)
            part = re.sub(r"(?<=[A-Za-z0-9])_(?=[A-Za-z0-9])", "_&#8203;", part)
            part = re.sub(r"(?<=[A-Za-z])/(?=[A-Za-z])", "/&#8203;", part)
            part = re.sub(r"(?<=\S)(?=（)|(?<=）)(?=）)", "&#8203;", part)
            parts[i] = re.sub(r"(?<=\d)–(?=\d)", "–&#8203;", part)
    return "".join(parts)


def unwrap_table_layout(text: str) -> str:
    text = re.sub(r"<code>.*?</code>(?:<br><code>.*?</code>)*", lambda m: "`" + html.unescape(
        re.sub(r"</?code>|<br>", "", m[0])) + "`", text)
    return text.replace("&shy;", "").replace("&#8203;", "")


def b_comparison(c: Ctx) -> str:
    head, rows, observation = comparison_details(c)
    return table([wrap_table_cell(cell) for cell in head],
                 [[wrap_table_cell(cell) for cell in row] for row in rows]) + "\n" + observation + "\n"


CI_TEMPLATE_URL = "https://github.com/e2b-dev/code-interpreter/tree/162a2a25b6a5ea5806749a437b96cbdc5bfc087e/template"


def ci_passed(m: dict) -> int:
    ci = m["e.latest.ci"]
    return sum(v["passed"] == ci["n"] for v in ci["steps"].values())


def b_runs(c: Ctx) -> str:
    m = c.m
    head = [c.t("Run", "实测"), c.t("Path", "路径"), c.t("Scenario", "场景"), c.t("Result", "结果")]
    rows = [
        ["`a-2026-10-09-agent`", "A", c.t("full agent, 3 runs", "完整 agent，跑 3 次"),
         c.t(f"cold {num(m['a.cold']['median'])} s, warm {num(m['a.warm']['median'])} s, resume → answer "
             f"{num(m['a.recover']['median'])} s (medians); vmm `{m['a.vmm']['value']}` in "
             f"{m['a.vmm']['count']}/{m['a.vmm']['n']}; history grew {m['a.state_kept']['count']}/{m['a.state_kept']['n']}",
             f"冷启动 {num(m['a.cold']['median'])} s、后续 {num(m['a.warm']['median'])} s、恢复到回答 "
             f"{num(m['a.recover']['median'])} s（中位数）；{m['a.vmm']['count']}/{m['a.vmm']['n']} 次 vmm 为 "
             f"`{m['a.vmm']['value']}`；历史持续增长 {m['a.state_kept']['count']}/{m['a.state_kept']['n']}")],
        ["`a-2026-10-09-attribution`", "A", c.t("create time by configuration", "按配置拆分创建耗时"),
         c.t(f"image, VNet or port alone {rng(m['a.attr.small'])} s; "
             f"adding the private Blob volume {rng(m['a.attr.vnetvolume'])} s",
             f"只加镜像、VNet 或端口 {rng(m['a.attr.small'])} s；"
             f"加私有 Blob 卷后 {rng(m['a.attr.vnetvolume'])} s")],
        ["`a-2026-10-09-late-mount`", "A", c.t("start first, mount Blob later", "先启动、后挂 Blob"),
         c.t(f"start {rng(m['a.late.create'])} s, then mount {rng(m['a.late.mount'])} s (n=2)",
             f"启动 {rng(m['a.late.create'])} s，再挂载 {rng(m['a.late.mount'])} s（n=2）")],
        ["`a-2026-09-27-setup`", "A", c.t("first deployment, wake on request", "首次部署，请求唤醒"),
         c.t(f"setup {num(m['a.setup']['value'])} s; a request to a stopped sandbox answered in "
             f"{num(m['a.wake_http']['value'])} s; kernel `{m['a.isolation']['guest_kernel']}`",
             f"部署 {num(m['a.setup']['value'])} s；向已停止的沙箱发请求，{num(m['a.wake_http']['value'])} s 后回答；"
             f"内核 `{m['a.isolation']['guest_kernel']}`")],
        ["`b-2026-09-27`", "B", c.t("deploy, new session, follow-ups; gateway model route",
                                   "部署、新会话、后续回答；gateway 模型路由"),
         c.t(f"deploy {num(m['b.deploy']['value'])} s; new session {num(m['b.cold_gateway']['value'])} s; "
             f"follow-ups {', '.join(num(v) for v in m['b.warm_gateway']['values'])} s",
             f"部署 {num(m['b.deploy']['value'])} s；新会话 {num(m['b.cold_gateway']['value'])} s；后续 "
             f"{', '.join(num(v) for v in m['b.warm_gateway']['values'])} s")],
        ["`b-2026-10-15-sessions`", "B", c.t("explicit session lifecycle, 3 runs", "显式会话生命周期，跑 3 次"),
         c.t(f"create → active {num(m['b.sess.create']['median'])} s, first answer {num(m['b.sess.first']['median'])} s, "
             f"follow-up {num(m['b.sess.warm']['median'])} s, stop → idle {num(m['b.sess.stop']['median'])} s, "
             f"resume → answer {num(m['b.sess.resume']['median'])} s (medians); file kept "
             f"{m['b.sess.state_kept']['files']}/{m['b.sess.state_kept']['n']}",
             f"创建 → active {num(m['b.sess.create']['median'])} s、第一个回答 {num(m['b.sess.first']['median'])} s、"
             f"后续 {num(m['b.sess.warm']['median'])} s、停止 → idle {num(m['b.sess.stop']['median'])} s、"
             f"恢复到回答 {num(m['b.sess.resume']['median'])} s（中位数）；文件保留 "
             f"{m['b.sess.state_kept']['files']}/{m['b.sess.state_kept']['n']}")],
        ["`c-2026-09-27`", "C", c.t("Kata Sandbox, pod loss, suspend/resume", "Kata Sandbox、pod 丢失、挂起/恢复"),
         c.t(f"pod kernel `{m['c.isolation']['guest_kernel']}` vs runc pod on the Ubuntu system pool "
             f"`{m['c.isolation']['system_node_kernel']}`; "
             f"pod lost → Ready {num(m['c.pod_lost']['value'])} s; resume → answer {num(m['c.resume_answer']['value'])} s",
             f"pod 内核 `{m['c.isolation']['guest_kernel']}`，Ubuntu 系统节点池的 runc pod 内核 "
             f"`{m['c.isolation']['system_node_kernel']}`；"
             f"pod 丢失后 {num(m['c.pod_lost']['value'])} s 就绪；恢复到回答 {num(m['c.resume_answer']['value'])} s")],
        ["`d-2026-09-29-placement`", "D", c.t("where a session runs", "会话跑在哪里"),
         c.t(f"every session pod `{m['d.placement']['runtime_class']}` on your node pool after NSG rule "
             f"`{m['d.placement']['nsg_rule']}`",
             f"加 NSG 规则 `{m['d.placement']['nsg_rule']}` 后，每个会话 pod 都是 `{m['d.placement']['runtime_class']}`，"
             "跑在你的节点池上")],
        ["`d-2026-09-29-perf`", "D", c.t("cold, warm, 4 and 8 at once", "冷启动、后续、4 和 8 并发"),
         c.t(f"cold {num(m['d.cold']['median'])} s, warm {num(m['d.warm']['median'])} s (medians); "
             f"4 at once {m['d.c4']['answered']}/{m['d.c4']['n']}, 8 at once {m['d.c8']['answered']}/{m['d.c8']['n']} "
             "answered (pool full)",
             f"冷启动 {num(m['d.cold']['median'])} s、后续 {num(m['d.warm']['median'])} s（中位数）；"
             f"4 并发 {m['d.c4']['answered']}/{m['d.c4']['n']}、8 并发 {m['d.c8']['answered']}/{m['d.c8']['n']} 回答（节点池已满）")],
        ["`d-2026-09-29-recovery`", "D", c.t("delete a session pod", "删除一个会话 pod"),
         c.t(f"replacement Ready in {num(m['d.pod_lost']['value'])} s; a different live session answered in "
             f"{num(m['d.other_session_followup']['value'])} s; deleted session continuity not tested",
             f"{num(m['d.pod_lost']['value'])} s 后替代 pod 就绪；另一个存活会话在 "
             f"{num(m['d.other_session_followup']['value'])} s 内回答；未测试被删会话的连续性")],
        ["`e-2026-10-14-agent`", "E", c.t("Prompt Agent + E2B, 3 runs + 20-run microbench", "Prompt Agent + E2B，跑 3 次 + 20 次微基准"),
         c.t(f"create {num(m['e.create']['median'])} s (on host {rng(m['e.bench20.create'])} s), "
             f"cold {num(m['e.cold']['median'])} s, warm {num(m['e.warm']['median'])} s, "
             f"resume → answer {num(m['e.recover']['median'])} s (medians); "
             f"VMM `{m['e.vmm']['value']}` in the host's process list; "
             f"history grew {m['e.state_kept']['count']}/{m['e.state_kept']['n']}",
             f"创建 {num(m['e.create']['median'])} s（本机 {rng(m['e.bench20.create'])} s）、"
             f"冷启动 {num(m['e.cold']['median'])} s、后续 {num(m['e.warm']['median'])} s、"
             f"恢复到回答 {num(m['e.recover']['median'])} s（中位数）；"
             f"宿主机进程列表里的 VMM 为 `{m['e.vmm']['value']}`；"
             f"历史持续增长 {m['e.state_kept']['count']}/{m['e.state_kept']['n']}")],
        ["`e-2026-10-14-perf`", "E", c.t("cold, warm, 4 and 8 at once, replacement", "冷启动、后续、4 和 8 并发、沙箱替换"),
         c.t(f"cold {num(m['e.d_cold']['median'])} s, warm {num(m['e.d_warm']['median'])} s (medians); "
             f"4 at once {m['e.c4']['answered']}/{m['e.c4']['n']}, 8 at once {m['e.c8']['answered']}/{m['e.c8']['n']} answered; "
             f"replacement Ready in {num(m['e.pod_lost']['value'])} s",
             f"冷启动 {num(m['e.d_cold']['median'])} s、后续 {num(m['e.d_warm']['median'])} s（中位数）；"
             f"4 并发 {m['e.c4']['answered']}/{m['e.c4']['n']}、8 并发 {m['e.c8']['answered']}/{m['e.c8']['n']} 回答；"
             f"{num(m['e.pod_lost']['value'])} s 后替代沙箱就绪")],
        ["`e-2026-10-15-latest`", "E", c.t("newest SDK; E2B's official code-interpreter template",
                                           "最新 SDK；E2B 官方 code-interpreter 模板"),
         c.t(f"e2b 2.56.0: history grew {m['e.latest.sdk.state_kept']['count']}/{m['e.latest.sdk.state_kept']['n']}, "
             f"create {num(m['e.latest.sdk.create']['median'])} s, resume {num(m['e.latest.sdk.resume']['median'])} s "
             f"(medians); code-interpreter built only after raising three host defaults; "
             f"{ci_passed(m)}/{len(m['e.latest.ci']['steps'])} checks passed in "
             f"{m['e.latest.ci']['n']}/{m['e.latest.ci']['n']} runs, JavaScript failed in all",
             f"e2b 2.56.0：历史持续增长 {m['e.latest.sdk.state_kept']['count']}/{m['e.latest.sdk.state_kept']['n']}，"
             f"创建 {num(m['e.latest.sdk.create']['median'])} s、恢复 {num(m['e.latest.sdk.resume']['median'])} s"
             f"（中位数）；code-interpreter 调大三项宿主机默认值后才建成；"
             f"{len(m['e.latest.ci']['steps'])} 项检查中 {ci_passed(m)} 项在 {m['e.latest.ci']['n']}/"
             f"{m['e.latest.ci']['n']} 次都通过，JavaScript 每次都失败")],
        ["`e-2026-10-15-multi`", "E", c.t("two independent E2B hosts: second host, at once, idle, host stop",
                                          "两台独立 E2B 主机：第二台、并发、空闲容量、停一台"),
         c.t(f"host b: history grew {m['e.multi.b.state_kept']['count']}/{m['e.multi.b.state_kept']['n']}, "
             f"create {num(m['e.multi.b.create']['median'])} s; at once {m['e.multi.one_host']['answered']}/"
             f"{m['e.multi.one_host']['n']} on one host, {m['e.multi.two_hosts']['answered']}/"
             f"{m['e.multi.two_hosts']['n']} on two; with host a's stack stopped, host b kept serving and "
             f"host a's paused sandbox could not resume on host b",
             f"host b：历史持续增长 {m['e.multi.b.state_kept']['count']}/{m['e.multi.b.state_kept']['n']}，"
             f"创建 {num(m['e.multi.b.create']['median'])} s；并发：单台 {m['e.multi.one_host']['answered']}/"
             f"{m['e.multi.one_host']['n']}，两台 {m['e.multi.two_hosts']['answered']}/{m['e.multi.two_hosts']['n']}；"
             "停掉 host a 的 E2B 后，host b 照常服务，host a 上暂停的沙箱在 host b 上恢复不了")],
    ]
    order = json.loads((ROOT / "evidence" / "claims.json").read_text(encoding="utf-8")).get("run_order")
    if not isinstance(order, list) or not all(isinstance(rid, str) for rid in order):
        raise RenderError("evidence/claims.json: run_order must be a list of run IDs")
    rows_by_id = {row[0].strip("`"): row for row in rows}
    if len(order) != len(rows) or set(order) != set(rows_by_id):
        raise RenderError("evidence/claims.json: run_order must list every results-table run exactly once")
    return table(head, [rows_by_id[rid] for rid in order])


# --- VALIDATION blocks ----------------------------------------------------------------------------

def v_a_agent_input(c: Ctx) -> str:
    a = c.runs["a-aca-2026-10-09/agent-runs.json"]
    i = a["inputs"]
    spec = a["sandbox_spec"]
    lines = [c.t(f"Configuration: {a['configuration']}; cpu {spec['cpu']}, memory {spec['memory']}, "
                 f"auto-suspend {spec['auto_suspend_seconds']} s in {spec['auto_suspend_mode']} mode.",
                 f"配置：{a['configuration']}；cpu {spec['cpu']}，memory {spec['memory']}，"
                 f"{spec['auto_suspend_mode']} 模式下空闲 {spec['auto_suspend_seconds']} s 自动挂起。"),
             c.t(f"Request: {i['request']}.", f"请求：{i['request']}。"),
             c.t(f"First answer: \"{i['first']}\"", f"第一个问题：\"{i['first']}\""),
             c.t(f"Every later turn: \"{i['warm']}\"", f"之后每一轮：\"{i['warm']}\"")]
    return quote(lines)


def v_a_agent(c: Ctx) -> str:
    a = c.runs["a-aca-2026-10-09/agent-runs.json"]
    head = [c.t("Run", "次"), c.t("Create → Running", "创建 → Running"), c.t("First answer", "第一个回答"),
            c.t("Cold", "冷启动"), c.t("Follow-up", "后续"), c.t("Stop", "停止"), c.t("Resume", "恢复"),
            c.t("Answer after resume", "恢复后回答"), c.t("Resume → answer", "恢复 → 回答"), c.t("Answers", "回答")]
    rows = []
    for r in a["runs"]:
        answers = " / ".join(str(r[k]["response"]) if k == "first" else str(r[k]["response"])
                             for k in ("first", "warm", "first_after_resume", "warm_after_resume"))
        rows.append([str(r["run"]), num(r["create_total_s"]), num(r["first"]["guest_s"]), num(r["cold_total_s"]),
                     num(r["warm"]["guest_s"]), num(r["stop_total_s"]), num(r["resume_total_s"]),
                     num(r["first_after_resume"]["guest_s"]), num(r["recover_total_s"]), answers])
    m = c.m
    rows.append([c.t("**median**", "**中位数**")] + [f"**{num(m[k]['median'])}**" for k in
                 ("a.create", "a.first_answer", "a.cold", "a.warm", "a.stop", "a.resume", "a.first_after_resume",
                  "a.recover")] + [""])
    return c.t("Seconds; answers are the agent's replies in order. Totals are added per run before taking the median; "
               "the independently reported column medians must not be added.\n\n",
               "单位为秒；最后一列是 agent 依次给出的回答。总耗时先在每次实测内相加，再取中位数；"
               "不能把各列独立统计的中位数相加。\n\n") + \
        table(head, rows, ["---"] + ["---:"] * 8 + ["---"])


def v_a_attr(c: Ctx) -> str:
    att = c.runs["a-aca-2026-10-09/create-attribution.json"]
    head = [c.t("Configuration", "配置"), c.t("What is added", "加了什么"), "n", c.t("Create → Running, s", "创建 → Running，s"),
            c.t("Median", "中位数")]
    rows = []
    for cfg in ("builtin", "image", "vnet", "port", "vnetvolume", "full"):
        r = c.m[f"a.attr.{cfg}"]
        rows.append([f"`{cfg}`", att["configs"][cfg], str(r["n"]), ", ".join(num(v) for v in r["values"]),
                     num(r["median"]) if "median" in r else c.t("— (n=2)", "—（n=2）")])
    s = c.m["a.attr.process_survived"]
    tail = c.t(f"\nGuest uptime after resume exceeded its pre-stop value in {s['count']} of {s['n']} sandboxes. "
               "This observation alone does not prove process-memory continuity.\n",
               f"\n{s['n']} 个沙箱中有 {s['count']} 个恢复后的 guest uptime 大于停止前的值。"
               "这个观察本身不能证明进程内存的连续性。\n")
    return table(head, rows, ["---", "---", "---:", "---", "---:"]) + tail


def v_a_late(c: Ctx) -> str:
    late = c.runs["a-aca-2026-10-09/late-mount.json"]
    head = [c.t("Run", "次"), c.t("Create without volume, s", "不带卷创建，s"), c.t("Attach Blob volume, s", "挂载 Blob 卷，s"),
            c.t("State after mount", "挂载后状态")]
    rows = [[str(r["run"]), num(r["create_total_s"]), num(r["add_volume_mount_s"]), r["state_after_mount"]]
            for r in late["runs"]]
    return table(head, rows, ["---", "---:", "---:", "---"])


def v_a_setup(c: Ctx) -> str:
    s = c.runs["a-aca-2026-09-27/setup-and-wake.json"]
    ev = s["events"]
    names = {"vnet_connection": c.t("VNet connection", "VNet 连接"), "disk_image": c.t("disk image from ACR", "从 ACR 构建磁盘镜像"),
             "volume": c.t("Blob volume", "Blob 卷"), "sandbox_create": c.t("sandbox create", "创建沙箱"),
             "reflect_in_sandbox": c.t("answer, timed inside", "回答（沙箱内计时）"),
             "suspend_sdk": c.t("stop (memory snapshot)", "停止（内存快照）"), "resume_sdk": c.t("resume", "恢复"),
             "reflect_after_resume": c.t("answer after resume", "恢复后回答"),
             "reflect_warm_after_resume": c.t("next answer", "下一轮回答"), "suspend_sdk_2": c.t("stop again", "再次停止"),
             "wake_on_http_request": c.t("HTTP request to the stopped sandbox", "向已停止的沙箱发 HTTP 请求"),
             "reflect_external_warm": c.t("next HTTP request", "下一个 HTTP 请求")}
    rows = [[c.t("sandbox group (Bicep)", "sandbox group（Bicep）"), "", num(s["sandbox_group_deploy_seconds"]), ""]]
    for e in ev:
        q = e.get("question") or e.get("query") or ""
        resp = e.get("response", e.get("state", ""))
        rows.append([names[e["step"]], f"\"{q}\"" if q else "", num(e["seconds"]), str(resp)])
    head = [c.t("Step", "步骤"), c.t("Input", "输入"), "s", c.t("Reply or state", "回答或状态")]
    iso = s["isolation_check"]
    tail = c.t(f"\nRead inside the sandbox: vmm_type `{iso['vmm_type']}`, kernel `{iso['guest_kernel']}`, "
               f"{iso['vcpus']} vCPU.\n",
               f"\n在沙箱内读到：vmm_type `{iso['vmm_type']}`，内核 `{iso['guest_kernel']}`，{iso['vcpus']} 个 vCPU。\n")
    return table(head, rows, ["---", "---", "---:", "---"]) + tail


def v_b(c: Ctx) -> str:
    b = c.runs["b-hosted-agent-2026-09-27/run.json"]
    head = [c.t("Step", "步骤"), c.t("Route to the model", "到模型的路由"), "s"]
    g, d = b["invoke_v1_gateway"], b["invoke_v2_direct"]
    rows = [["`azd ai agent init`", "", num(b["azd_ai_agent_init_seconds"])],
            [c.t("`azd deploy`, version 1", "`azd deploy`，版本 1"), "gateway", num(b["deploy_v1_gateway"]["seconds"])],
            [c.t("new session → answer", "新会话 → 回答"), "gateway", num(g["new_session_seconds"])],
            [c.t("follow-up turns", "后续回答"), "gateway", ", ".join(num(v) for v in g["warm_seconds"])],
            [c.t("`azd deploy`, version 2", "`azd deploy`，版本 2"), "direct", num(b["deploy_v2_direct"]["seconds"])],
            [c.t("new session → answer", "新会话 → 回答"), "direct", num(d["new_session_seconds"])],
            [c.t("follow-up turns", "后续回答"), "direct", ", ".join(num(v) for v in d["warm_seconds"])]]
    return table(head, rows, ["---", "---", "---:"])


def v_b_sessions(c: Ctx) -> str:
    s = c.runs["b-sessions-2026-10-15/sessions.json"]
    head = [c.t("Run", "次"), c.t("Create → active", "创建 → active"), c.t("First answer", "第一个回答"),
            c.t("Follow-up", "后续"), c.t("Stop → idle", "停止 → idle"), c.t("Answer after stop", "停止后回答"),
            c.t("Next answer", "再下一轮"), c.t("File kept", "文件保留"), c.t("Answers", "回答")]
    rows = []
    for r in s["runs"]:
        create = r["create"]["total_s"] + ((r["create"].get("wait_active") or {}).get("seconds") or 0)
        stop = r["stop"]["total_s"] + r["stop"]["wait_stopped"]["seconds"]
        answers = " / ".join(str(r[k]["response"]) for k in ("first", "warm", "resume", "warm_after_resume"))
        rows.append([str(r["run"]), num(round(create, 3)), num(r["first"]["total_s"]), num(r["warm"]["total_s"]),
                     num(round(stop, 3)), num(r["resume"]["total_s"]), num(r["warm_after_resume"]["total_s"]),
                     c.t("yes", "是") if r["marker_after_resume"]["matches"] is True else c.t("no", "否"), answers])
    m = c.m
    rows.append([c.t("**median**", "**中位数**")] + [f"**{num(m[k]['median'])}**" for k in
                 ("b.sess.create", "b.sess.first", "b.sess.warm", "b.sess.stop", "b.sess.resume",
                  "b.sess.warm_after_resume")] + ["", ""])
    codes: dict[str, int] = {}
    for e in s["http_log"]:
        codes[str(e["status"])] = codes.get(str(e["status"]), 0) + 1
    retried = sum(len(v["attempts"]) > 1 for r in s["runs"] for v in r.values()
                  if isinstance(v, dict) and isinstance(v.get("attempts"), list))
    en_codes = ", ".join(f"{code} ×{n}" for code, n in sorted(codes.items()))
    zh_codes = "、".join(f"{code} ×{n}" for code, n in sorted(codes.items()))
    tail = c.t(f"\n{len(s['http_log'])} HTTP attempts: {en_codes}; "
               + ("none retried" if not retried else f"{retried} calls retried") + ".\n",
               f"\n共 {len(s['http_log'])} 次 HTTP 尝试：{zh_codes}；"
               + ("没有重试" if not retried else f"{retried} 次调用有重试") + "。\n")
    return c.t("Seconds, client wall time; the last column is the agent's replies in order.\n\n",
               "单位为秒，客户端计时；最后一列是 agent 依次给出的回答。\n\n") + \
        table(head, rows, ["---"] + ["---:"] * 6 + ["---", "---"]) + tail


def v_c(c: Ctx) -> str:
    r = c.runs["c-aks-agent-sandbox-2026-09-27/run.json"]
    head = [c.t("Step", "步骤"), c.t("Observed", "观察结果")]
    k = r["kata_isolation"]
    rows = [[c.t("`prepare-agent-sandbox.sh`", "`prepare-agent-sandbox.sh`"), f"{num(r['prepare_script_seconds'])} s"],
            [c.t("Blob private link", "Blob 私有链接"), f"{num(r['storage_private_link_seconds'])} s"],
            [c.t("`kubectl apply` → Sandbox Ready", "`kubectl apply` → Sandbox Ready"),
             f"{num(r['sandbox_apply_to_ready_seconds'])} s"],
            [c.t("first answer, second answer", "第一个、第二个回答"),
             f"{num(r['reflect']['first_seconds'])} s, {num(r['reflect']['second_seconds'])} s"
             + c.t(f"; context remembered: {str(r['reflect']['remembers_context']).lower()}",
                   f"；记住上下文：{str(r['reflect']['remembers_context']).lower()}")],
            [c.t("`uname -r` in the Sandbox pod / in a runc pod", "Sandbox pod / runc pod 中的 `uname -r`"),
             f"`{k['sandbox_kernel']}` / `{k['runc_pod_kernel']}`"],
            [c.t("delete the pod → Ready again", "删除 pod → 重新就绪"),
             f"{num(r['pod_delete_to_ready_seconds'])} s" + c.t(f", state restored: {str(r['state_restored_after_pod_delete']).lower()}",
                                                               f"，状态恢复：{str(r['state_restored_after_pod_delete']).lower()}")],
            [c.t("`operatingMode: Suspended` → pod gone", "`operatingMode: Suspended` → pod 消失"),
             f"{num(r['suspend']['pod_gone_seconds'])} s" + c.t(f"; health while suspended HTTP {r['suspend']['health_while_suspended']}",
                                                               f"；挂起期间健康检查 HTTP {r['suspend']['health_while_suspended']}")],
            [c.t("`operatingMode: Running` → Ready / LB 200 / answer", "`operatingMode: Running` → Ready / LB 200 / 回答"),
             f"{num(r['resume']['sandbox_ready_seconds'])} / {num(r['resume']['lb_health_200_seconds'])} / "
             f"{num(r['resume']['first_answer_seconds'])} s"]]
    return table(head, rows)


def v_d_input(c: Ctx) -> str:
    b = c.runs["d-byoaks-2026-09-29/bench.json"]
    i = b["inputs"]
    rtt = c.m["d.client_rtt"]
    lines = [c.t(f"Request: {b['request']}.", f"请求：{b['request']}。"),
             c.t(f"New sessions: \"{i['cold']}\" (n = 1, 2, 3)", f"新会话：\"{i['cold']}\"（n = 1、2、3）"),
             c.t(f"One session: \"{i['warm_first']}\", then \"{i['warm_followup_1']}\", then \"{i['warm_followup_n']}\" "
                 "(n = 1, 2)",
                 f"同一会话：\"{i['warm_first']}\"，然后 \"{i['warm_followup_1']}\"，再 \"{i['warm_followup_n']}\"（n = 1、2）"),
             c.t(f"At once, per session: \"{i['scale_turn1']}\", then \"{i['scale_turn2']}\"",
                 f"并发时每个会话：\"{i['scale_turn1']}\"，然后 \"{i['scale_turn2']}\""),
             c.t(f"Client: {b['client']}; recorded round trip {rng(rtt)} ms.",
                 f"客户端：{b['client']}；记录到的往返时延 {rng(rtt)} ms。")]
    return quote(lines)


def v_d_cold(c: Ctx) -> str:
    b = c.runs["d-byoaks-2026-09-29/bench.json"]
    e = c.runs["d-byoaks-2026-09-29/cold-early.json"]
    fresh = set(e["first_pod_on_fresh_node_s"])
    head = [c.t("Start (UTC)", "开始（UTC）"), c.t("Node", "节点"), c.t("Answer", "回答"), c.t("New session → answer, s", "新会话 → 回答，s"),
            c.t("Pod created → Ready, s", "pod 创建 → Ready，s")]
    rows = []
    for r in e["runs"]:
        rows.append([r["start_utc"], c.t("no image yet", "尚无镜像") if r["wall_s"] in fresh else c.t("image cached", "镜像已缓存"),
                     r["answer"], num(r["wall_s"]), c.t("not paired", "未配对")])
    for t in b["cold_turns"]:
        rows.append([t["started_utc"][:8], c.t("image cached", "镜像已缓存"), t["answer"], num(t["wall_s"]),
                     num(t["pod"]["create_to_ready_s"])])
    w = b["warm_turns"][0]
    rows.append([w["started_utc"][:8], c.t("image cached", "镜像已缓存"), w["answer"], num(w["wall_s"]),
                 c.t("not paired", "未配对")])
    m = c.m
    tail = c.t(f"\nWith the image cached: {c.med('d.cold')}. First pod on a node without the image: "
               f"{c.vals('d.cold_fresh')}. Session pods created → Ready across the run: "
               f"{', '.join(num(v) for v in m['d.pod_ready']['values'])} s with the image cached, "
               f"{', '.join(num(v) for v in m['d.pod_ready_fresh']['values'])} s on a fresh node.\n",
               f"\n镜像已缓存：{c.med('d.cold')}。节点上还没有镜像时的第一个 pod：{c.vals('d.cold_fresh')}。"
               f"本次所有会话 pod 从创建到 Ready：镜像已缓存 {', '.join(num(v) for v in m['d.pod_ready']['values'])} s，"
               f"新节点 {', '.join(num(v) for v in m['d.pod_ready_fresh']['values'])} s。\n")
    return table(head, rows, ["---", "---", "---", "---:", "---:"]) + tail


def v_d_warm(c: Ctx) -> str:
    b = c.runs["d-byoaks-2026-09-29/bench.json"]
    head = [c.t("Turn", "轮次"), c.t("Answer", "回答"), c.t("Client wall, s", "客户端耗时，s")]
    rows = []
    for k, t in enumerate(b["warm_turns"]):
        label = c.t("1 (new session)", "1（新会话）") if k == 0 else str(k + 1)
        rows.append([label, t["answer"], num(t["wall_s"])])
    tail = c.t(f"\nThe same model called directly from the same client, without an agent: {c.med('d.model_direct')}. "
               "This baseline used low reasoning effort; it is not a matched agent-configuration benchmark.\n",
               f"\n同一客户端不经 agent 直接调用同一个模型：{c.med('d.model_direct')}。"
               "该基线使用 low reasoning effort，不是与 agent 配置完全匹配的基准测试。\n")
    return table(head, rows, ["---", "---", "---:"]) + tail


def v_d_scale(c: Ctx) -> str:
    head = [c.t("At once", "并发"), c.t("Answered", "回答"), c.t("Refused", "拒绝"), c.t("Refusal", "拒绝原因"),
            c.t("Refused after, s", "拒绝耗时，s")]
    rows = []
    for n in (4, 8):
        r = c.m[f"d.c{n}"]
        rows.append([str(n), f"{r['answered']}/{r['n']}" + (f" ({', '.join(num(v) for v in r['answered_s'])} s)" if r["answered_s"] else ""),
                     f"{r['refused']}/{r['n']}", ", ".join(f"`{x}`" for x in r["refused_codes"]),
                     f"{num(r['refused_after_s'][0])}–{num(r['refused_after_s'][1])}"])
    cap = c.m["d.capacity"]
    tail = c.t(f"\nWhen the refusals began, {cap['max_sessions']} session pods were alive on {cap['n']} "
               f"`{cap['node_sku']}` nodes, at most {cap['per_node']} per node, and no node had 500m CPU left.\n",
               f"\n开始拒绝时，{cap['n']} 个 `{cap['node_sku']}` 节点上共有 {cap['max_sessions']} 个会话 pod，"
               f"单节点最多 {cap['per_node']} 个，没有节点还剩 500m CPU。\n")
    return table(head, rows, ["---:", "---", "---", "---", "---:"]) + tail


def v_d_recovery(c: Ctx) -> str:
    r = c.runs["d-byoaks-2026-09-29/recovery.json"]
    f = r["followup_after_kill"]
    rows = [[c.t("session pod deleted (UTC)", "删除会话 pod（UTC）"), r["pod_deleted_utc"]],
            [c.t("replacement pod Ready after", "替代 pod 就绪耗时"), f"{num(r['replacement_ready_s'])} s"],
            [c.t("follow-up on a different live session", "另一个存活会话的后续回答"),
             f"HTTP {f['http']}, {num(f['wall_s'])} s, \"{f['answer']}\"" +
             c.t(f", that session kept its state: {str(f['state_preserved']).lower()}",
                 f"，该会话保留了自身状态：{str(f['state_preserved']).lower()}")]]
    return table([c.t("Step", "步骤"), c.t("Observed", "观察结果")], rows)


def v_d_placement(c: Ctx) -> str:
    p = c.runs["d-byoaks-2026-09-29/placement.json"]
    pod, rule = p["session_pod"], p["nsg_rule_added"]
    flows = "; ".join(f"{f['source']} → :443 {f['access']}" for f in p["ip_flow_verify_before_fix"])
    req = pod["containers"][0]["resources"]["requests"]
    rows = [[c.t("IP flow verify before the fix", "修复前 IP flow verify"), flows],
            [c.t("rule added to the subnet NSG", "在子网 NSG 上新增的规则"),
             f"`{rule['name']}`, {c.t('priority', '优先级')} {rule['priority']}, {rule['direction']} {rule['access']} "
             f"{rule['protocol']} {rule['source']} → {rule['destination']}:{rule['destination_port']}"],
            [c.t("first session after the fix", "修复后的第一个会话"),
             f"HTTP {p['first_session_after_fix']['http']}, \"{p['first_session_after_fix']['answer']}\", "
             f"{p['first_session_after_fix']['client_wall_seconds']} s {c.t('on the client', '客户端耗时')}"],
            [c.t("its session pod", "它的会话 pod"),
             f"runtimeClassName `{pod['runtimeClassName']}`, {c.t('owner', '属主')} {pod['owner_kind']}, "
             f"{c.t('requests', 'requests')} {req['cpu']} / {req['memory']}, overhead {pod['overhead']['memory']}, "
             f"{c.t('init containers', 'init 容器')} {', '.join(pod['init_containers'])}"],
            [c.t("scheduled → Ready", "调度 → Ready"), f"{c.m['d.placement']['scheduled_to_ready_s']} s"],
            [c.t("session pods at the 18:15 recheck", "18:15 复查时的会话 pod"),
             c.t(f"{c.m['d.placement']['kata_pods_at_recheck']} of {len(p['session_pods_at_recheck'])} Running with "
                 "`kata-vm-isolation`",
                 f"{len(p['session_pods_at_recheck'])} 个中 {c.m['d.placement']['kata_pods_at_recheck']} 个为 Running 且是 "
                 "`kata-vm-isolation`")],
            [c.t("two turns at the recheck", "复查时的两轮对话"),
             " → ".join(f"\"{t['answer']}\"" for t in p["recheck_two_turns"])],
            [c.t("kernel of the Kata pool nodes", "Kata 节点池的节点内核"), f"`{c.m['d.node_kernel']['value']}`"]]
    return table([c.t("Check", "检查项"), c.t("Observed", "观察结果")], rows)


def v_e_agent_input(c: Ctx) -> str:
    ea = c.runs["e-e2b-2026-10-14/agent-runs.json"]
    i = ea["inputs"]
    iso = ea["isolation_check"]
    lines = [c.t(f"Host VM: {ea['host_vm_sku']}; E2B `base` template ({iso['vcpus']} vCPU, {iso['memory_mb']} MB, "
                 "Firecracker memory + disk snapshot via `beta_pause`).",
                 f"宿主机 VM：{ea['host_vm_sku']}；E2B `base` 模板（{iso['vcpus']} vCPU，{iso['memory_mb']} MB，"
                 "经 `beta_pause` 保存 Firecracker 内存+磁盘快照）。"),
             c.t(f"Versions: E2B Python SDK `{ea['sdk']}`; E2B Embed runtime `{ea['e2b_runtime_commit'][:7]}`.",
                 f"版本：E2B Python SDK `{ea['sdk']}`；E2B Embed 运行时 `{ea['e2b_runtime_commit'][:7]}`。"),
             c.t(f"Request: {i['request']}.", f"请求：{i['request']}。"),
             c.t(f"Agent instructions: \"{ea['agent']['instructions']}\"", f"Agent 指令：\"{ea['agent']['instructions']}\""),
             c.t(f"Its one function tool `{ea['agent']['tools'][0]['name']}(python_code)`: "
                 f"\"{ea['agent']['tools'][0]['description']}\"",
                 f"唯一的函数工具 `{ea['agent']['tools'][0]['name']}(python_code)`："
                 f"\"{ea['agent']['tools'][0]['description']}\""),
             c.t(f"First answer: \"{i['first']}\"", f"第一个问题：\"{i['first']}\""),
             c.t(f"Every later turn: \"{i['warm']}\"", f"之后每一轮：\"{i['warm']}\"")]
    return quote(lines)


def v_e_agent(c: Ctx) -> str:
    ea = c.runs["e-e2b-2026-10-14/agent-runs.json"]
    head = [c.t("Run", "次"), c.t("Create → Running", "创建 → Running"), c.t("First answer", "第一个回答"),
            c.t("Cold", "冷启动"), c.t("Follow-up", "后续"), c.t("Pause", "暂停"), c.t("Resume", "恢复"),
            c.t("Answer after resume", "恢复后回答"), c.t("Resume → answer", "恢复 → 回答"), c.t("Answers", "回答")]
    rows = []
    for r in ea["runs"]:
        answers = " / ".join(str(r[k]["response"]) for k in ("first", "warm", "first_after_resume", "warm_after_resume"))
        rows.append([str(r["run"]), num(r["create_total_s"]), num(r["first"]["guest_s"]), num(r["cold_total_s"]),
                     num(r["warm"]["guest_s"]), num(r["stop_total_s"]), num(r["resume_total_s"]),
                     num(r["first_after_resume"]["guest_s"]), num(r["recover_total_s"]), answers])
    m = c.m
    rows.append([c.t("**median**", "**中位数**")] + [f"**{num(m[k]['median'])}**" for k in
                 ("e.create", "e.first_answer", "e.cold", "e.warm", "e.stop", "e.resume", "e.first_after_resume",
                  "e.recover")] + [""])
    iso = ea["isolation_check"]
    tail = c.t(f"\nOn-host 20-sandbox microbenchmark (zero WAN RTT): create {c.rng_n('e.bench20.create')}, "
               f"warm command {c.rng_n('e.bench20.warm_cmd')}, pause {c.rng_n('e.bench20.pause')}, "
               f"resume {c.rng_n('e.bench20.resume')}. VMM `{iso['vmm_type']}` `{iso['firecracker_version']}` "
               f"from the host's process list; guest kernel `{iso['guest_kernel']}` from `uname -r` inside the "
               f"sandbox; host kernel `{iso['host_kernel']}`.\n",
               f"\n本机 20 次沙箱微基准（零跨网 RTT）：创建 {c.rng_n('e.bench20.create')}，"
               f"热命令 {c.rng_n('e.bench20.warm_cmd')}，暂停 {c.rng_n('e.bench20.pause')}，"
               f"恢复 {c.rng_n('e.bench20.resume')}。VMM `{iso['vmm_type']}` `{iso['firecracker_version']}` "
               f"来自宿主机进程列表；guest 内核 `{iso['guest_kernel']}` 来自沙箱内的 `uname -r`；"
               f"宿主机内核 `{iso['host_kernel']}`。\n")
    return table(head, rows, ["---"] + ["---:"] * 8 + ["---"]) + tail


def v_e_perf_input(c: Ctx) -> str:
    ep = c.runs["e-e2b-2026-10-14/perf.json"]
    i = ep["inputs"]
    driver = next(s for s in ep["_sources"] if s["role"] == "benchmark driver")
    w = i["warm"]
    lines = [c.t(f"Request: {ep['request']}; agent instructions and tool as in `e-2026-10-14-agent`.",
                 f"请求：{ep['request']}；agent 指令和工具与 `e-2026-10-14-agent` 相同。"),
             c.t(f"New sessions: \"{i['cold']}\" (n = 1, 2, 3, 4, 5)", f"新会话：\"{i['cold']}\"（n = 1、2、3、4、5）"),
             c.t(f"One session: \"{w[0]}\", then \"{w[1]}\", then \"{w[2]}\", then \"{w[3]}\"",
                 f"同一会话：\"{w[0]}\"，然后 \"{w[1]}\"，再 \"{w[2]}\"，再 \"{w[3]}\""),
             c.t(f"At once, per session: \"{i['scale'][0]}\", then \"{i['scale'][1]}\"",
                 f"并发时每个会话：\"{i['scale'][0]}\"，然后 \"{i['scale'][1]}\""),
             c.t(f"Replacement: a live session ran \"{i['recovery'][0]}\"; after another sandbox was killed and "
                 f"replaced, it ran \"{i['recovery'][1]}\"",
                 f"替换：一个存活会话先发 \"{i['recovery'][0]}\"；另一个沙箱被删除并替换后，再发 \"{i['recovery'][1]}\""),
             c.t(f"Driver: the author's private script `{driver['file']}` (SHA-256 `{driver['sha256'][:12]}…` in the "
                 "record); `tools/measure_e2b.py perf` sends the same prompts with the same agent and clocks.",
                 f"驱动：作者的私有脚本 `{driver['file']}`（SHA-256 `{driver['sha256'][:12]}…` 记在记录里）；"
                 "`tools/measure_e2b.py perf` 用同样的 agent、问题和计时。")]
    return quote(lines)


def v_e_cold(c: Ctx) -> str:
    ep = c.runs["e-e2b-2026-10-14/perf.json"]
    head = [c.t("Start (UTC)", "开始（UTC）"), c.t("Answer", "回答"),
            c.t("Sandbox created → Ready, s", "沙箱创建 → Ready，s"),
            c.t("Agent turn, s", "Agent 轮次，s"), c.t("New session → answer, s", "新会话 → 回答，s")]
    rows = [[t["started_utc"][:8], t["answer"], num(t["sandbox_create_to_ready_s"]),
             num(t["agent_turn_s"]), num(t["wall_s"])] for t in ep["cold_turns"]]
    tail = c.t(f"\nAcross the 5 cold runs: sandbox create → Ready {c.med('e.d_sandbox_ready')}, "
               f"Prompt Agent turn {c.med('e.d_agent_turn')}, end-to-end new session → answer {c.med('e.d_cold')}.\n",
               f"\n5 次冷启动汇总：沙箱创建 → Ready {c.med('e.d_sandbox_ready')}，"
               f"Prompt Agent 轮次 {c.med('e.d_agent_turn')}，端到端新会话 → 回答 {c.med('e.d_cold')}。\n")
    return table(head, rows, ["---", "---", "---:", "---:", "---:"]) + tail


def v_e_warm(c: Ctx) -> str:
    ep = c.runs["e-e2b-2026-10-14/perf.json"]
    head = [c.t("Turn", "轮次"), c.t("Answer", "回答"), c.t("Sandbox tool, s", "沙箱工具耗时，s"),
            c.t("Turn, s", "轮次耗时，s")]
    rows = []
    for k, t in enumerate(ep["warm_turns"]):
        label = c.t("1 (new session; includes the sandbox create)", "1（新会话；含沙箱创建）") if k == 0 else str(k + 1)
        rows.append([label, t["answer"], num(t["sandbox_tool_s"]), num(t["wall_s"])])
    return table(head, rows, ["---", "---", "---:", "---:"])


def v_e_scale(c: Ctx) -> str:
    m = c.m
    head = [c.t("At once", "并发"), c.t("Answered", "回答"), c.t("Refused", "拒绝"),
            c.t("Sandbox create + turn 1, s", "沙箱创建 + 第 1 轮，s")]
    rows = []
    for n in (4, 8):
        r = c.m[f"e.c{n}"]
        rows.append([str(n), f"{r['answered']}/{r['n']}", f"{r['refused']}/{r['n']}",
                     ", ".join(num(v) for v in r["answered_s"])])
    rec = c.runs["e-e2b-2026-10-14/perf.json"]["recovery"]
    f = rec["followup_on_live_session"]
    tail = c.t(f"\nSandbox replacement after `kill`: new Firecracker sandbox Ready in {num(rec['replacement_ready_s'])} s; "
               f"follow-up on a live session HTTP {f['http']}, {num(f['wall_s'])} s, \"{f['answer']}\", "
               f"state preserved: {str(f['state_preserved']).lower()}. No count of live micro-VMs is published for "
               "this run: the driver counted them with `pgrep -fc`, which also counted its own shell.\n",
               f"\n`kill` 删除沙箱后的替换：新 Firecracker 沙箱在 {num(rec['replacement_ready_s'])} s 内就绪；"
               f"另一个存活会话的追问 HTTP {f['http']}，{num(f['wall_s'])} s，\"{f['answer']}\"，"
               f"保留状态：{str(f['state_preserved']).lower()}。本次不公布同时运行的 micro-VM 数：驱动用 `pgrep -fc` "
               "计数，把它自己的 shell 也算了进去。\n")
    return table(head, rows, ["---:", "---", "---", "---"]) + tail


def e_turn_table(c: Ctx, runs_: list[dict], prefix: str) -> str:
    head = [c.t("Run", "次"), c.t("Create → Running", "创建 → Running"), c.t("First answer", "第一个回答"),
            c.t("Cold", "冷启动"), c.t("Follow-up", "后续"), c.t("Pause", "暂停"), c.t("Resume", "恢复"),
            c.t("Answer after resume", "恢复后回答"), c.t("Resume → answer", "恢复 → 回答"), c.t("Answers", "回答")]
    rows = []
    for r in runs_:
        answers = " / ".join(str(r[k]["response"]) for k in ("first", "warm", "first_after_resume", "warm_after_resume"))
        rows.append([str(r["run"]), num(r["create_total_s"]), num(r["first"]["wall_s"]), num(r["cold_total_s"]),
                     num(r["warm"]["wall_s"]), num(r["stop_total_s"]), num(r["resume_total_s"]),
                     num(r["first_after_resume"]["wall_s"]), num(r["recover_total_s"]), answers])
    m = c.m
    rows.append([c.t("**median**", "**中位数**")] + [f"**{num(m[f'{prefix}.{k}']['median'])}**" for k in
                 ("create", "first", "cold", "warm", "pause", "resume", "first_after_resume", "recover")] + [""])
    return table(head, rows, ["---"] + ["---:"] * 8 + ["---"])


def v_e_multi_input(c: Ctx) -> str:
    mu = c.runs["e-e2b-2026-10-15/multi.json"]
    i, t = mu["inputs"], mu["tool"]
    lines = [c.t(f"Tool: `{t['file']}` (SHA-256 `{t['sha256'][:12]}…`); the agent runs on host b used the revision "
                 f"`{t['agent_runs_revision_sha256'][:12]}…`, which did not yet record HTTP statuses. Agent instructions, "
                 "tool schema and prompts as in `e-2026-10-14-agent` and `e-2026-10-14-perf`.",
                 f"工具：`{t['file']}`（SHA-256 `{t['sha256'][:12]}…`）；host b 上的 agent 实测用的是前一版 "
                 f"`{t['agent_runs_revision_sha256'][:12]}…`，那一版还不记录 HTTP 状态。agent 指令、工具定义和问题与 "
                 "`e-2026-10-14-agent`、`e-2026-10-14-perf` 相同。")]
    install = {
        "a": c.t("installed on 2026-10-14 for `e-2026-10-14-agent`, deallocated overnight, then started and brought up "
                 "once with `docker compose up -d --wait`, as E2B's guide asks after a reboot",
                 "2026-10-14 为 `e-2026-10-14-agent` 安装，夜间释放；开机后按 E2B 指南对重启的要求执行一次 "
                 "`docker compose up -d --wait`"),
        "b": c.t(f"installed on 2026-10-15 with README step 7 (`compose.yaml` and `.env` at `588e5b9`, both SHA-256 OK) "
                 f"in {mu['hosts']['b']['install_time']['total_s']} s",
                 f"2026-10-15 按 README 第 7 步安装（`588e5b9` 的 `compose.yaml` 和 `.env`，SHA-256 均校验通过），用时 "
                 f"{mu['hosts']['b']['install_time']['total_s']} s")}
    for name in ("a", "b"):
        h = mu["hosts"][name]
        disk = h["os_disk"].replace(", ", " · ")
        lines.append(c.t(f"Host {name}: `{h['vm_sku']}`, zone `{h['zone']}`, host kernel `{h['host_kernel']}`, Docker "
                         f"`{h['docker']}`, OS disk `{disk}`, `HUGEPAGES={h['hugepages']}`; {install[name]}.",
                         f"Host {name}：`{h['vm_sku']}`，zone `{h['zone']}`，宿主机内核 `{h['host_kernel']}`，Docker "
                         f"`{h['docker']}`，系统盘 `{disk}`，`HUGEPAGES={h['hugepages']}`；{install[name]}。"))
    lines += [c.t("Network: both hosts in one subnet and zone; the tool ran on host a and reached host b's ports `3000` "
                  "and `3002` over the private network; host b's NSG admitted only host a's private address on those "
                  "two ports and no other inbound traffic.",
                  "网络：两台主机在同一子网和可用区；工具在 host a 上运行，经私网访问 host b 的 `3000` 和 `3002` 端口；"
                  "host b 的 NSG 只允许 host a 的私网地址访问这两个端口，不放行其他入站流量。"),
              c.t(f"Agent runs on host b: \"{i['first']}\", then \"{i['count']}\" 3 times, pausing for "
                  f"{i['resume_wait_s']} s after the second turn.",
                  f"host b 上的 agent 实测：\"{i['first']}\"，然后 3 次 \"{i['count']}\"，第二轮后暂停 "
                  f"{i['resume_wait_s']} s。"),
              c.t(f"One host at once, on host a: 8 sessions; new session \"{i['cold'].format(i=1)}\" and one session "
                  f"with \"{i['warm'][0]}\" before it.",
                  f"单台并发（host a）：8 个会话；在此之前先跑一个新会话 \"{i['cold'].format(i=1)}\" 和一个以 "
                  f"\"{i['warm'][0]}\" 开头的会话。"),
              c.t(f"At once, per session: \"{i['scale'][0]}\", then \"{i['scale'][1]}\".",
                  f"并发时每个会话：\"{i['scale'][0]}\"，然后 \"{i['scale'][1]}\"。"),
              c.t(f"Host stop: on each host one live session (\"{i['live'][0]}\") and one paused sandbox "
                  f"(\"{i['paused'][0]}\", `{{h}}` = the host's name); then `docker compose stop` on host a with the VM "
                  f"running, later `docker compose up -d --wait`; reads back \"{i['live'][1]}\" and "
                  f"\"{i['paused'][1]}\".",
                  f"停一台：每台各有一个存活会话（\"{i['live'][0]}\"）和一个暂停的沙箱（\"{i['paused'][0]}\"，"
                  f"`{{h}}` 为主机名）；然后在 host a 上执行 `docker compose stop`（VM 不关），之后再 "
                  f"`docker compose up -d --wait`；读回时发 \"{i['live'][1]}\" 和 \"{i['paused'][1]}\"。"),
              c.t("Idle capacity: `Sandbox.create(\"base\")` on host a, one after another with no model and no "
                  "command, until a create was refused, 3 times.",
                  "空闲容量：在 host a 上逐个 `Sandbox.create(\"base\")`，不调模型、不跑命令，直到创建被拒，共 3 次。")]
    return quote(lines)


def v_e_multi_agent(c: Ctx) -> str:
    mu = c.runs["e-e2b-2026-10-15/multi.json"]
    rr = mu["agent_runs_host_b"]
    slow = max(rr, key=lambda r: r["cold_total_s"])
    tail = c.t(f"\nHistory inside the sandbox grew 1, 2, 3, 4 in {c.m['e.multi.b.state_kept']['count']} of "
               f"{len(rr)} runs. Run {slow['run']}'s slow turns were model turns: its first answer took "
               f"{num(slow['first']['wall_s'])} s, of which the sandbox command took "
               f"{num(slow['first']['sandbox_tool_s'])} s.\n",
               f"\n沙箱内的历史在 {len(rr)} 次中有 {c.m['e.multi.b.state_kept']['count']} 次按 1、2、3、4 增长。"
               f"第 {slow['run']} 次慢在模型轮次：第一个回答用了 {num(slow['first']['wall_s'])} s，其中沙箱命令只占 "
               f"{num(slow['first']['sandbox_tool_s'])} s。\n")
    return e_turn_table(c, rr, "e.multi.b") + tail


def v_e_multi_scale(c: Ctx) -> str:
    mu = c.runs["e-e2b-2026-10-15/multi.json"]
    head = [c.t("Phase", "阶段"), c.t("Sessions at once", "同时会话"), c.t("Answered", "回答"),
            c.t("Refused", "拒绝"), c.t("Refusal cause", "拒绝原因"), c.t("Sandbox create, s", "沙箱创建，s"),
            c.t("Whole session, s", "整个会话，s"), c.t("Model HTTP attempts", "模型 HTTP 尝试")]
    rows = []
    for key, level, label in (("e.multi.one_host", mu["perf_host_a"]["at_once"], c.t("host a alone", "仅 host a")),
                              ("e.multi.two_hosts", mu["two_hosts_at_once"], c.t("hosts a and b", "host a 和 b"))):
        r = c.m[key]
        ok = [s for s in level["sessions"] if s.get("remembered")]
        create = [s["sandbox_create_to_ready_s"] for s in ok]
        sess = [s["session_s"] for s in ok]
        per = c.t(", ".join(f"{h} {v['answered']}/{v['sessions']}" for h, v in r["per_host"].items()),
                  "，".join(f"{h} {v['answered']}/{v['sessions']}" for h, v in r["per_host"].items()))
        codes = ", ".join(f"{code} ×{n}" for code, n in sorted(r["model_http_statuses"].items()))
        rows.append([label, str(r["n"]), f"{r['answered']}/{r['n']} ({per})", f"{r['refused']}/{r['n']}",
                     f"`{r['refusal_cause']}`", f"{num(min(create), 3)}–{num(max(create), 3)}",
                     f"{num(min(sess))}–{num(max(sess))}", codes])
    tail = c.t("\nThe client spread the 16 sessions over the two hosts in turn. Each refusal was E2B's "
               "`500: Failed to place sandbox`, with `cannot allocate memory` from the orchestrator behind it; the "
               "model's 2 HTTP 500 answers were retried within their turns and those sessions answered.\n",
               "\n客户端把 16 个会话轮流分给两台主机。每次拒绝都是 E2B 的 `500: Failed to place sandbox`，"
               "背后是编排器的 `cannot allocate memory`；模型返回的 2 次 HTTP 500 都在同一轮内重试成功，这些会话照常回答。\n")
    return table(head, rows, ["---", "---:", "---", "---", "---", "---:", "---:", "---"]) + tail


def v_e_multi_idle(c: Ctx) -> str:
    mu = c.runs["e-e2b-2026-10-15/multi.json"]
    hp = c.m["e.multi.hugepages"]
    head = [c.t("Run", "次"), c.t("Created before the refusal", "被拒前创建成功"), c.t("Refusal", "拒绝原因"),
            c.t("Hugepages taken: before → at the refusal", "已占大页：开始 → 被拒时"),
            c.t("After killing them", "全部删除后")]
    rows = []
    for r in mu["idle_capacity_host_a"]:
        ok = [x for x in r["creates"] if x["ok"]]
        rows.append([str(r["run"]), str(len(ok)), f"`{r['refusal']}`",
                     f"{r['before']['hugepages_taken']} → {ok[-1]['hugepages_taken']}",
                     c.t(f"{r['after_kill']['hugepages_taken']} pages, {r['after_kill']['sandboxes_left']} sandboxes",
                         f"{r['after_kill']['hugepages_taken']} 页，{r['after_kill']['sandboxes_left']} 个沙箱")])
    free = hp["pool"] - hp["postgres"]
    tail = c.t(f"\nPages are 2 MiB. Each `base` sandbox (512 MiB) reserved {hp['per_sandbox']} pages when it was "
               f"created, idle or not. The pool is {hp['pool']} pages and postgres in the Compose stack holds "
               f"{hp['postgres']}, which leaves {free} pages: room for {hp['fit']} sandboxes. Run 1 stopped earlier "
               "on a different error.\n",
               f"\n每页 2 MiB。每个 `base` 沙箱（512 MiB）在创建时就预留 {hp['per_sandbox']} 页，不论是否空闲。"
               f"大页池共 {hp['pool']} 页，Compose 栈里的 postgres 占 {hp['postgres']} 页，剩下 {free} 页，"
               f"能放下 {hp['fit']} 个沙箱。第 1 次因为另一个错误提前停止。\n")
    return table(head, rows, ["---:", "---:", "---", "---", "---"]) + tail


def v_e_multi_hostloss(c: Ctx) -> str:
    hl = c.runs["e-e2b-2026-10-15/multi.json"]["host_loss"]
    b, a, back = hl["after_loss"]["b"], hl["after_loss"]["a"], hl["after_restart"]["a"]

    def res(x: dict, value: str | None = None) -> str:
        if x["ok"]:
            return c.t(f"ok, {num(x['seconds'])} s", f"成功，{num(x['seconds'])} s") + (f", \"{value}\"" if value else "")
        err = x["error"]
        short = "connection refused" if "Connection refused" in err else err.split(":")[0] + ": " + \
            err.split(": ", 1)[1].replace("<sandbox id>", "…")
        return c.t(f"failed: `{short}`", f"失败：`{short}`")

    rows = [[c.t("host b, live session: read its file", "host b，存活会话：读回文件"),
             res(b["live_session_read"], b["live_session_read"].get("value"))],
            [c.t("host b: new session", "host b：新会话"), res(b["new_session"], b["new_session"]["value"]["answer"])],
            [c.t("host b: resume host a's paused sandbox", "host b：恢复 host a 上暂停的沙箱"),
             res(b["connect_lost_hosts_paused_sandbox"])],
            [c.t("host a, stopped: create", "host a 停止中：创建"), res(a["create"])],
            [c.t("host a, stopped: resume its own paused sandbox", "host a 停止中：恢复自己暂停的沙箱"),
             res(a["connect_own_paused_sandbox"])],
            [c.t("host a, after restart: resume its own paused sandbox", "host a 重启后：恢复自己暂停的沙箱"),
             res(back["resume_own_paused_sandbox"], back["resume_own_paused_sandbox"].get("value"))],
            [c.t("host a, after restart: the sandbox that was running when it stopped",
                 "host a 重启后：停止时正在运行的沙箱"), res(back["live_sandbox_before_loss"])],
            [c.t("host a, after restart: new session", "host a 重启后：新会话"),
             res(back["new_session"], back["new_session"]["value"]["answer"])],
            [c.t("`docker compose stop` / `docker compose up -d --wait`", "`docker compose stop` / `docker compose up -d --wait`"),
             f"{num(hl['stop']['seconds'])} s / {num(hl['start']['seconds'])} s"]]
    return table([c.t("Check", "检查项"), c.t("Observed", "观察结果")], rows)


def v_e_latest_input(c: Ctx) -> str:
    la = c.runs["e-e2b-2026-10-15/latest.json"]
    s, ci = la["sdk_check"], la["code_interpreter"]
    r = ci["template_resources"]
    lines = [c.t(f"SDK check: `{s['tool']['file']} {s['tool']['command']}` with `{s['sdk']}` (Python {s['python']}), "
                 f"tool SHA-256 `{s['tool']['sha256'][:12]}…`; \"{s['inputs']['first']}\", then "
                 f"\"{s['inputs']['count']}\" 3 times, pausing for {s['inputs']['resume_wait_s']} s after the "
                 "second turn.",
                 f"SDK 检查：`{s['tool']['file']} {s['tool']['command']}`，`{s['sdk']}`（Python {s['python']}），"
                 f"工具 SHA-256 `{s['tool']['sha256'][:12]}…`；\"{s['inputs']['first']}\"，然后 3 次 "
                 f"\"{s['inputs']['count']}\"，第二轮后暂停 {s['inputs']['resume_wait_s']} s。"),
             c.t(f"code-interpreter: template `{ci['template']}` ({r['vcpus']} vCPU, {r['memory_mb']} MB) from "
                 f"[`e2b-dev/code-interpreter@162a2a2`]({CI_TEMPLATE_URL}), built with its unchanged "
                 f"`template/build_prod.py` (build environment `e2b 2.32.0`); checked with "
                 f"`e2b-code-interpreter {ci['client']['e2b-code-interpreter']}` and `{ci['check_tool']['file']}`.",
                 f"code-interpreter：模板 `{ci['template']}`（{r['vcpus']} vCPU，{r['memory_mb']} MB），来自 "
                 f"[`e2b-dev/code-interpreter@162a2a2`]({CI_TEMPLATE_URL})，用其原样的 `template/build_prod.py` 构建"
                 f"（构建环境 `e2b 2.32.0`）；用 `e2b-code-interpreter {ci['client']['e2b-code-interpreter']}` 和 "
                 f"`{ci['check_tool']['file']}` 检查。"),
             c.t("Cells, in order, with no model: \"x = 1\", \"x+=1; x\", a pandas sum, a matplotlib plot, JavaScript "
                 "\"[1, 2, 3].reduce((a, b) => a + b)\", \"1/0\", then after pause and resume \"x\".",
                 "按顺序执行的代码单元（不经模型）：\"x = 1\"、\"x+=1; x\"、pandas 求和、matplotlib 画图、JavaScript "
                 "\"[1, 2, 3].reduce((a, b) => a + b)\"、\"1/0\"，暂停并恢复后再执行 \"x\"。")]
    return quote(lines)


def v_e_latest_sdk(c: Ctx) -> str:
    la = c.runs["e-e2b-2026-10-15/latest.json"]
    rr = la["sdk_check"]["runs"]
    codes: dict[str, int] = {}
    for r in rr:
        for k in ("first", "warm", "first_after_resume", "warm_after_resume"):
            for code in r[k]["http_statuses"]:
                codes[str(code)] = codes.get(str(code), 0) + 1
    joined = ", ".join(f"{code} ×{n}" for code, n in sorted(codes.items()))
    tail = c.t(f"\nModel HTTP attempts: {joined}. History grew 1, 2, 3, 4 in "
               f"{c.m['e.latest.sdk.state_kept']['count']} of {len(rr)} runs; no sandbox was left.\n",
               f"\n模型 HTTP 尝试：{joined}。历史在 {len(rr)} 次中有 {c.m['e.latest.sdk.state_kept']['count']} 次按 "
               "1、2、3、4 增长；没有遗留沙箱。\n")
    return e_turn_table(c, rr, "e.latest.sdk") + tail


def v_e_latest_build(c: Ctx) -> str:
    ci = c.runs["e-e2b-2026-10-15/latest.json"]["code_interpreter"]
    head = [c.t("Attempt", "次"), "HUGEPAGES", c.t("Build workspace, MiB", "构建工作空间，MiB"),
            c.t("OS disk, GB", "系统盘，GB"), c.t("Result", "结果"), c.t("Seconds", "秒")]
    why_by_attempt = {
        1: c.t("`mmap memfd: cannot allocate memory` while resuming the build VM",
               "恢复构建 VM 时 `mmap memfd: cannot allocate memory`"),
        2: c.t("`pip install` in the build VM: `[Errno 28] No space left on device`",
               "构建 VM 里的 `pip install`：`[Errno 28] No space left on device`"),
        3: c.t("below 8 GiB free on the OS disk, which also holds the E2B database",
               "系统盘剩余不到 8 GiB，而 E2B 的数据库也在这块盘上"),
    }
    rows = []
    for b in ci["builds"]:
        at = f"{b['step']}/{b['steps']}"
        if b["result"] == "failed":
            what = c.t(f"failed at step {at}: {why_by_attempt[b['attempt']]}",
                       f"第 {at} 步失败：{why_by_attempt[b['attempt']]}")
        elif b["result"] == "stopped":
            what = c.t(f"stopped by us at step {at}: {why_by_attempt[b['attempt']]}",
                       f"我们在第 {at} 步停止：{why_by_attempt[b['attempt']]}")
        else:
            what = c.t(f"built, {at} steps; steps {b['cached_steps'][0]}–{b['cached_steps'][1]} from attempt 3's cache",
                       f"建成，{at} 步；第 {b['cached_steps'][0]}–{b['cached_steps'][1]} 步用第 3 次的缓存")
        rows.append([str(b["attempt"]), str(b["hugepages"]), str(b["build_disk_mb"]), str(b["os_disk_gb"]), what,
                     num(b["seconds"])])
    a3 = next(b for b in ci["builds"] if b["result"] == "stopped")
    a4 = next(b for b in ci["builds"] if b["result"] == "built")
    used = a4["os_disk_free_gib_before"] - a4["os_disk_free_gib_after"]
    ch = {x["to"]: x for x in ci["changes_for_the_build"]}
    hp, ws, disk = ch[4096], ch[8192], ch[128]
    tail = c.t(f"\nBy step {a3['step']} attempt {a3['attempt']} had written {a3['written_mib']['templates']} MiB of "
               f"templates and {a3['written_mib']['orchestrator']} MiB under the orchestrator's directory, with "
               f"{a3['os_disk_free_mib']} MiB left on the OS disk; attempt {a4['attempt']} then used {used} GiB "
               f"(free {a4['os_disk_free_gib_before']} → {a4['os_disk_free_gib_after']} GiB). What we changed: "
               f"`HUGEPAGES` in the Compose `.env` {hp['from']} → {hp['to']}, then `docker compose up -d --wait`; the "
               f"test team's build workspace (`disk_mb`) {ws['from']} → {ws['to']} MiB, by adding one row to Embed's "
               f"internal `project_limits` table; the OS disk {disk['from']} → {disk['to']} GB (deallocate, snapshot, "
               "`az disk update --size-gb`, start).\n",
               f"\n到第 {a3['step']} 步时，第 {a3['attempt']} 次已写入 {a3['written_mib']['templates']} MiB 模板和 "
               f"{a3['written_mib']['orchestrator']} MiB 编排器目录数据，系统盘只剩 {a3['os_disk_free_mib']} MiB；"
               f"第 {a4['attempt']} 次又用掉 {used} GiB（剩余 {a4['os_disk_free_gib_before']} → "
               f"{a4['os_disk_free_gib_after']} GiB）。我们改了这些：Compose `.env` 里的 `HUGEPAGES` {hp['from']} → "
               f"{hp['to']}，再执行 `docker compose up -d --wait`；测试团队的构建工作空间（`disk_mb`）{ws['from']} → "
               f"{ws['to']} MiB，做法是往 Embed 内部的 `project_limits` 表加一行；系统盘 {disk['from']} → {disk['to']} GB"
               "（释放、拍快照、`az disk update --size-gb`、开机）。\n")
    return table(head, rows, ["---:", "---:", "---:", "---:", "---", "---:"]) + tail


def v_e_latest_ci(c: Ctx) -> str:
    ci = c.runs["e-e2b-2026-10-15/latest.json"]["code_interpreter"]
    m = c.m["e.latest.ci"]
    head = [c.t("Step", "步骤"), c.t("Passed", "通过"), c.t("Seconds, min–max", "秒，最小–最大"),
            c.t("Observed in run 4", "第 4 次的观察")]
    last = {s["step"]: s for s in ci["check_runs"][-1]["steps"]}
    rows = []
    for name, v in m["steps"].items():
        s = last[name]
        seen = s.get("error", {}).get("value") if isinstance(s.get("error"), dict) else None
        if seen is None:
            obs = s.get("observed") or {}
            seen = obs.get("text") if obs.get("text") else (obs.get("error") or
                                                              ("png" if obs.get("results") else ""))
        rows.append([f"`{name}`", f"{v['passed']}/{m['n']}", f"{num(v['min'], 3)}–{num(v['max'], 3)}",
                     f"`{seen}`" if seen else ""])
    js = ci["javascript_failure"]
    labels = [c.t("JavaScript as the first cell of a new sandbox, then the same cell again",
                  "新沙箱的第一个单元就是这段 JavaScript，再执行一次同样的单元"),
              c.t("a Python cell first, then the JavaScript cell (the order of the check)",
                  "先执行一个 Python 单元，再执行这段 JavaScript（检查里的顺序）"),
              c.t("the JavaScript cell with a leading semicolon", "在这段 JavaScript 前加一个分号")]
    if len(js["repro"]) != len(labels):
        raise RenderError("e-2026-10-15-latest: expected 3 JavaScript reproduction cases")
    repro = []
    for label, case in zip(labels, js["repro"]):
        cells = " → ".join((f"`{x['text']}`" if x["text"] else f"`{x['error']['name']}`" if x["error"] else c.t("ok", "成功"))
                           for x in case["cells"])
        repro.append(f"{label}: {cells}" if c.lang == "en" else f"{label}：{cells}")
    src = js["source"]
    tail = c.t(f"\nWhy JavaScript failed, reproduced in new sandboxes: " + "; ".join(repro) + f". In `{src['file']}` at "
               f"`{src['repo'].split('@')[1][:7]}`, line 160 writes `process.env['KEY'] = 'VALUE'` with no semicolon, "
               "and lines 351–361 put those lines before the user code on a context's first execution, so code that "
               "starts with `[` continues the last of them. Cells that start with `console.log` or a number ran.\n",
               f"\nJavaScript 失败的原因（在新沙箱里复现）：" + "；".join(repro) + f"。在 `{src['repo'].split('@')[1][:7]}` 的 "
               f"`{src['file']}` 里，第 160 行写出的 `process.env['KEY'] = 'VALUE'` 不带分号，第 351–361 行在一个上下文"
               "第一次执行时把这些语句放在用户代码前面，于是以 `[` 开头的代码接到了最后一句上。以 `console.log` 或数字"
               "开头的代码可以正常执行。\n")
    return table(head, rows, ["---", "---:", "---:", "---"]) + tail


BLOCKS = {
    "comparison": b_comparison, "runs": b_runs,
    "a-agent-input": v_a_agent_input, "a-agent": v_a_agent, "a-attr": v_a_attr, "a-late": v_a_late,
    "a-setup": v_a_setup, "b-run": v_b, "b-sessions": v_b_sessions, "c-run": v_c, "d-input": v_d_input, "d-cold": v_d_cold,
    "d-warm": v_d_warm, "d-scale": v_d_scale, "d-recovery": v_d_recovery, "d-placement": v_d_placement,
    "e-agent-input": v_e_agent_input, "e-agent": v_e_agent, "e-perf-input": v_e_perf_input,
    "e-cold": v_e_cold, "e-warm": v_e_warm, "e-scale": v_e_scale,
    "e-latest-input": v_e_latest_input, "e-latest-sdk": v_e_latest_sdk, "e-latest-build": v_e_latest_build,
    "e-latest-ci": v_e_latest_ci,
    "e-multi-input": v_e_multi_input, "e-multi-agent": v_e_multi_agent, "e-multi-scale": v_e_multi_scale,
    "e-multi-idle": v_e_multi_idle, "e-multi-hostloss": v_e_multi_hostloss,
}


def value(metrics: dict, key: str) -> str:
    metric, _, field = key.rpartition(".")
    if metric not in metrics:
        raise RenderError(f"inline value {key}: unknown metric {metric}")
    rec = metrics[metric]
    if field == "range":
        return rng(rec)
    if field not in rec:
        raise RenderError(f"inline value {key}: metric has no field {field}")
    v = rec[field]
    return v if isinstance(v, str) else num(v, 3 if rec.get("unit") == "USD/h" else 2)


def render_page(text: str, lang: str, metrics: dict, runs: dict) -> str:
    c = Ctx(metrics, runs, lang)

    def block(mo: re.Match) -> str:
        name = mo.group(2)
        if name not in BLOCKS:
            raise RenderError(f"unknown generated block {name}")
        return mo.group(1) + BLOCKS[name](c) + mo.group(4)

    text = BLOCK_RE.sub(block, text)
    return VALUE_RE.sub(lambda mo: f"<!--v:{mo.group(1)}-->{value(metrics, mo.group(1))}<!--/v-->", text)


def load_inputs() -> tuple[dict, dict]:
    runs, index = bm.load_runs()
    fresh = bm.render(bm.build(runs, index))
    if not bm.OUT.exists() or bm.OUT.read_text(encoding="utf-8") != fresh:
        raise RenderError("evidence/measurements.json differs from a fresh build; run tools/build_measurements.py")
    return json.loads(fresh)["metrics"], runs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="compare instead of writing")
    args = ap.parse_args(argv)
    try:
        metrics, runs = load_inputs()
        changed = []
        for name, lang in PAGES.items():
            path = ROOT / name
            old = path.read_text(encoding="utf-8")
            new = render_page(old, lang, metrics, runs)
            if new != old:
                changed.append(name)
                if not args.check:
                    path.write_text(new, encoding="utf-8", newline="\n")
    except (RenderError, bm.BuildError, KeyError, FileNotFoundError) as exc:
        print(f"RENDER FAIL {exc}", file=sys.stderr)
        return 1
    if args.check and changed:
        print(f"RENDER FAIL {', '.join(changed)} differ from a fresh render; run tools/render_docs.py", file=sys.stderr)
        return 1
    print(f"RENDER {'PASS' if args.check else 'WRITTEN'} {len(PAGES)} pages" + (f", updated {changed}" if changed and not args.check else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
