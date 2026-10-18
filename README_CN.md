# 在 Azure 上托管 agent 沙箱的五种方式：ACA Sandboxes、Foundry Hosted Agent、AKS + agent-sandbox、BYO-AKS、E2B on Azure VM

[![Paths](https://img.shields.io/badge/paths-A%20%C2%B7%20B%20%C2%B7%20C%20%C2%B7%20D%20%C2%B7%20E-0078D4)](#目的)
[![Measured](https://img.shields.io/badge/measured-East%20US%202%2C%202026--09--22%20to%2010--18-0078D4)](#实现效果)
[![Docs CI](https://github.com/xinyuwei-david/Azure-Agent-Sandbox-Hosting/actions/workflows/docs-ci.yml/badge.svg)](https://github.com/xinyuwei-david/Azure-Agent-Sandbox-Hosting/actions/workflows/docs-ci.yml)

作者：魏新宇 · [English](README.md)

## 目的

在 Azure 上用 micro-VM（带独立内核的轻量虚拟机）隔离 AI agent 有两种做法：把整个有状态 agent 放进会话自己的 micro-VM（方案 A–D），或者让 agent 跑在 Foundry 里，只把它的工具要执行的代码放进 micro-VM 沙箱（方案 E）。不论哪种，都要决定由谁来运行这个 micro-VM 和它的生命周期：交给一个托管服务、交给 Foundry，还是放在你自己的 AKS 节点或 Azure VM 上。五条路径各有取舍，如果把沙箱启动、外挂私有存储卷和模型回答揉成一个数字，光看产品页或粗粒度总耗时很难横向比较。本仓库用同一套可比的有状态交互口径测试五条路径，把每个阶段的耗时单独拆开，给出每条路径的复现步骤，并列出实测结果。A 和 C 共用 workshop 的 reflection agent；B 是另一个采用 Agent Framework 和 ResponsesHostServer 的 agent；D 使用产品组的私有预览 sample；E 使用 Foundry Prompt Agent，它的函数工具用 E2B 的 Code Interpreter 在 Azure VM 上的 Firecracker 沙箱里执行 agent 的代码，所以这不是相同容器的基准测试：

| 问题 | A · ACA Sandboxes | B · Foundry hosted agent | C · AKS + agent-sandbox | D · BYO-AKS | E · E2B on Azure VM |
|---|---|---|---|---|---|
| 状态 | GA（2026-09-23） | GA（2026-06） | Pod Sandboxing GA（2025-11-18）；agent-sandbox v0.5.2 为开源项目 | **私有预览** | E2B Embed 开源版（`588e5b9`），运行在 Azure Gen2 VM 上 |
| 谁负责会话生命周期 | ACA 服务 | Foundry | 你自己：控制器、网关、空闲回收 | Foundry，运行在你的集群上 | 你自己：你的 VM 上的 E2B 编排器，作为 Foundry agent 工具被调用 |
| 会话的 micro-VM 跑在哪里 | 服务托管的算力 | 微软托管的算力 | 你的 Kata 节点池 | 你的 Kata 节点池 | 你开启嵌套虚拟化（`/dev/kvm`）的 Azure VM |
| 带内存快照的挂起 | 支持 | 不支持：空闲后释放算力，恢复时还原 `$HOME` 和 `/files` | 不保存内存快照：你修改 `operatingMode`；pod 被删除，文件状态从 Blob 恢复 | 不保存内存快照：会话 API 的 `:stop` 结束会话 pod；下一次请求启动新 pod，停止前写入的文件仍在（2026-10-18） | 支持：`beta_pause` 保存 Firecracker 内存和磁盘快照（`vm_state` + `mem_file`） |
| 挂起再恢复后保留数据，是否必须挂外置存储 | 不需要（可选）：Memory 快照同时保住内存和磁盘；不挂卷时对话保住 3/3（2026-10-18） | 不需要（可选）：平台保留 `$HOME` 和 `/files`；停止前写入的文件读回 3/3 | **必须**：挂起会删除 pod，也不保存内存快照；挂 Blob PVC 时对话接着继续 3/3。不挂卷时状态随 pod 一起删除（按 Kubernetes 规则推断，未实测） | 不需要（可选）：`:stop` 结束会话 pod，停止前写入的文件在新 pod 上读回 3/3（2026-10-18） | 不需要（可选）：暂停快照存在宿主 VM 的系统盘上，在第二台主机上恢复不了（`e-2026-10-15-multi`）；沙箱内的历史持续增长 3/3 |
| 可选规格 / 节点 SKU（文档） | XS：0.25 vCPU / 0.5 GB<br>S：0.5 vCPU / 1 GB<br>M（默认）：1 vCPU / 2 GB<br>L：2 vCPU / 4 GB<br>XL：4 vCPU / 8 GB | 0.5 vCPU / 1 GiB<br>1 vCPU / 2 GiB<br>2 vCPU / 4 GiB<br>不选择 VM SKU | 支持 Kata 的 Gen2 VM SKU，如 Dsv3 系列；须使用 Azure Linux 并支持嵌套虚拟化 | 在预览开通条件内选择 Kata 节点 SKU；具体可选清单须向产品组确认 | 支持嵌套虚拟化的 Gen2 VM SKU，如 `Standard_D4ds_v7`；E2B 的 `code-interpreter-v1` 模板为 2 vCPU / 2 GiB（`base`：2 vCPU / 512 MB） |
| 适合的场景 | 要每用户一个 micro-VM、要快照、不想管集群 | 希望 Foundry 托管一切，且它的限制对你没有影响 | 必须自己掌控节点、网络和控制面 | 既要 Foundry 的 agent 平台，**又**要求会话跑在你自己的节点上 | 希望在自有 VM 上获得 100 ms 以内的 Firecracker 创建与内存快照，并由 Foundry agent 作为工具调用 |

“外置存储”这一行只说同一个沙箱或会话的挂起和恢复。如果沙箱或会话删除后还要保留数据，或者多个沙箱要共用数据，五条路径都要规划外置存储或数据库；删除沙箱或会话后的情况我们没有测。

产品能力来自 Microsoft Learn，状态来自下文链接的官方公告，实测声明来自我们的运行记录，最后一行是我们的选型建议。一般企业 agent 在 B 的限制可接受时先选 B。对于需要按用户长期运行、要内存快照又不想管集群的场景，先选 A。只有执行节点必须归你时才选 C、D 或 E；如果要求 Foundry 直接把会话 pod 调度到你的 AKS 集群上选 D，如果希望由 Foundry Prompt Agent 按工具调用单台 Azure VM 上自建的 Firecracker 沙箱则选 E。E2B Embed [按设计只有一台机器](https://github.com/e2b-dev/runtime/blob/588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/README.md#when-one-node-is-not-enough)：多几台 VM 就是多几套独立安装，由你的客户端把会话分给它们（`e-2026-10-15-multi`）；要在自己的云账号里用多节点，E2B 提供的是由 E2B 运维的 Bring Your Own Cloud，我们没有测。

可选项分四类：[A 的沙箱资源档位](https://learn.microsoft.com/azure/container-apps/sandboxes-overview#resource-tiers)、[B 的沙箱规格](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents#sandbox-sizes)、[C/D 的节点 VM SKU](https://learn.microsoft.com/azure/aks/use-pod-sandboxing)，以及 [E 的宿主 Azure Gen2 VM SKU 加 E2B 模板配额](https://github.com/e2b-dev/runtime/tree/588e5b9500b0987bc5a700d91483b03f0ae7d2a2)。节点或宿主 VM SKU 不是单会话分配规格；在 C/D 中每个 Kata 会话还受 pod 的 requests、limits 和开销限制，在 E 中每个 Firecracker 沙箱受 E2B 模板配额（`code-interpreter-v1`：`2` vCPU / `2048` MB；`base`：`2` vCPU / `512` MB）限制。方案 E 同时作为客户在自有 Azure VM 上自建开源 Firecracker 的参照基线，用来与 Azure 原生方案（A–D）横向验证沙箱启动、内存快照恢复与并发密度。节点 SKU 的可用性与配额取决于区域和订阅，D 还须满足预览开通条件。

状态来源：[A 的 GA 公告](https://techcommunity.microsoft.com/blog/appsonazureblog/azure-container-apps-sandboxes-now-generally-available/4559125)、[B 的 GA 公告](https://azure.microsoft.com/updates?id=563596)、[C 的 Pod Sandboxing GA](https://azure.microsoft.com/updates?id=526237)，以及 [E 的开源 E2B Embed 运行时（`588e5b9`）](https://github.com/e2b-dev/runtime/tree/588e5b9500b0987bc5a700d91483b03f0ae7d2a2)；agent-sandbox 和 E2B Embed 本身是开源项目，不是 Azure 托管服务。对 C/D，[Kata 只提供计算隔离](https://learn.microsoft.com/azure/aks/concepts-pod-sandboxing)，不隔离控制面、存储与数据路径，也不限制 cluster-admin 的权限。对 E，宿主机 `/dev/kvm` 上的 Firecracker（`v1.14-0.2.0`）提供每个沙箱的 micro-VM 隔离，但宿主机 OS、Docker 守护进程、E2B API 鉴权和子网 NSG 规则均由你自己负责。

<img src="images/architecture-zh.png" width="900" alt="A 到 E 五列，每列包含客户端入口、微软托管区和你的订阅。A：ACA Sandboxes 服务和沙箱 micro-VM，你的订阅里有 sandbox group、镜像仓库和 Blob 卷。B：Foundry Agent Service 和每会话沙箱，你的订阅里有项目和 Application Insights。C：AKS 控制面，你的订阅里有控制器、Kata pod VM、Kata 节点池和 Blob PVC。D：Foundry Agent Service，你的订阅里有子网 NSG、foundry-system、每会话 Kata pod VM，以及镜像仓库和存储。E：Foundry Agent Service，你的订阅里有带 E2B Embed Compose 栈的 Azure VM、每沙箱 Firecracker micro-VM，以及存放模板和快照的 VM 系统盘。">

这张图说明的是：各组件归谁所有、micro-VM 的边界在哪里。A、C、D、E 的落点来自我们的读回，B 的 VM 级隔离边界来自 Learn。图里没有画网络细节、身份流转和模型网关。

**各方案执行模型与官方并发配额对比（有状态 Agent 容器直跑 vs 工具沙箱）。** 方案 A–D 把整个有状态 agent 容器跑在会话的 micro-VM 内；而方案 E 把 agent 放在 Foundry 托管控制面，仅在执行代码或工具时按需调用独立的 micro-VM 沙箱：

| 执行形态 | Agent 进程在哪里跑 | micro-VM 里跑的是什么 | 官方并发上限与配额文档说明 | 会话期间是否始终占有一个微型 VM | 空闲暂停与缩零能力 |
|---|---|---|---|---|---|
| **A / B / C / D（有状态 Agent 容器跑在沙箱内）** | 直接跑在微型 VM 沙箱内（与会话 `1:1` 绑定） | 整个 agent 容器（ACA Cloud Hypervisor / Foundry 沙箱 / AKS Kata） | **A**：默认 [500 并发活跃核](https://sandboxes.azure.com/docs/sandboxes/limits)（[标准上限 2,000 核](https://learn.microsoft.com/azure/container-apps/quotas#sandboxes-and-express-quotas)，本订阅实查 `20,000` 核；`3,000` 请求/分钟；已挂起沙箱不占配额）<br>**B**：[按活跃会话 1:1 动态创建](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents#scaling-and-right-sizing)（单会话 `20` GiB 磁盘、单个上传文件 `50` MB）<br>**C / D**：受限于你的 AKS Kata 节点池 vCPU/内存配额 | **是** —— 活跃会话期间该微型 VM 保持 Running | **A**：内存快照挂起（`1.58–2.83` s 恢复）<br>**B**：空闲超时或调 `:stop` 释放算力并保留 `$HOME`<br>**C**：改 `operatingMode` 删 pod 并从 Blob 恢复<br>**D**：会话 `:stop` 结束会话 pod，下一次请求启动新 pod |
| **E（Foundry Agent Service + E2B on Azure VM 工具沙箱）** | Foundry 托管控制面（无服务器，按模型 token 计费） | 只有 agent 的工具要执行的代码：你的 Azure Gen2 VM（`/dev/kvm`）上的 Firecracker 微型 VM | 一套 Embed 安装就是一台 VM，受它的大页池限制：在 `Standard_D4ds_v7` 上，`HUGEPAGES=4096` 能放 `3` 个空闲的 `code-interpreter-v1` 沙箱（每个 2 GiB），2026-10-17 `8` 个会话同时进行时回答 `3/8`；Compose 默认的 `2048` 只能放 `1` 个（`base`：`7` 个）；再加一台独立 VM 就多一个它自己的大页池（`base`：两台 VM 上 `14/16`，2026-10-15）；两套安装之间没有共享调度 | **按需** —— 仅在调用 `run_in_e2b_sandbox` 工具时运行；轮次间可 `beta_pause` | 单沙箱支持内存快照暂停（2 GiB 的 `code-interpreter-v1` 沙箱 <!--v:e.ci.resume.median-->0.64<!--/v--> s 恢复），但底层宿主 Azure VM（`0.344` USD/h）需常驻运行 |

**ToC 与高并发选型核心权衡：冷启动、预热池（Warm Pool）与全生命周期成本（ACA vs AKS Spot vs E2B）：**
- **冷启动速度与预热池（Warm Pool）：** 面向 ToC 用户的交互式场景最关注两点：冷启动速度与成本。如果不配预热池，基于 Kubernetes 的沙箱（C/D）在新节点上会遭遇拉取镜像或挂卷的冷启动耗时，除非自行维护预热池（如 `agent-sandbox` 的 `SandboxWarmPool`）。ACA Sandboxes（A，不挂私有 Blob 卷时 <!--v:a.nv.create.median-->1.35<!--/v--> s 进入 Running、<!--v:a.nv.cold.median-->4.86<!--/v--> s 给出第一个回答，均为中位数）由平台维护预热池；运行在自有 Azure VM 上的 E2B（E）则通过本地模板快照启动 2 GiB 的 `code-interpreter-v1` Firecracker micro-VM，中位数 <!--v:e.ci.create.median-->0.08<!--/v--> s（5 个冷启动会话中 <!--v:e.ci.d_sandbox_ready.range-->0.069–0.13<!--/v--> s）。
- **成本结构 —— 生命周期管理 + 状态保持 + 恢复速度（ACA 强项） vs Spot 竞价节点（AKS/VM 强项）：** 面对带有大量空闲长尾的潮汐式会话，**ACA（方案 A）在生命周期管理、状态保持与恢复速度上更强**：挂起后自动保存完整内存与磁盘快照（不挂卷 <!--v:a.attr.resume_small.range-->1.58–2.79<!--/v--> s / 带 Blob 卷 <!--v:a.resume.median-->2.83<!--/v--> s 恢复），Stopped 期间不收 CPU/内存费且不占并发活跃核数配额。反过来，**AKS（方案 C）与自建 VM（方案 E）可以使用 [Azure Spot 节点池 / Spot VM](https://learn.microsoft.com/azure/aks/spot-node-pool)**（或预留实例 RI / Savings Plan）大幅压低持续高负载或可容忍中断场景下的单核小时成本——这是按 Serverless 档位计费的 ACA 不具备的；若用 AKS Spot 跑有状态沙箱，业务需自行处理 Spot 驱逐时的状态落盘与重建。

## 实现效果

看结果时要用到的几个词：

| 术语 | 含义 |
|---|---|
| 冷启动（cold） | 新会话或新沙箱从创建到返回第一个回答 |
| 后续回答（warm） | 同一个运行中会话里的下一轮对话 |
| 恢复（resume） | 会话已完成挂起：发起恢复 → 第一个回答；不含停止和空闲等待 |
| pod 丢失（pod lost） | 删除会话所在的 pod 或沙箱，由 Kubernetes 或调用方重新创建 |
| micro-VM | 每个沙箱、会话或 pod 一个带独立 guest 内核的轻量虚拟机（AKS 上是 Kata Containers；ACA 沙箱内读到的 VMM 是 Cloud Hypervisor；E2B 在 KVM 上运行 Firecracker） |

**每条路径的 micro-VM 跑在哪里。** A、C、D、E 来自实测读回，B 来自 Learn 写明的隔离边界：

| | A · ACA Sandboxes | B · Foundry hosted agent | C · AKS + agent-sandbox | D · BYO-AKS | E · E2B on Azure VM |
|---|---|---|---|---|---|
| 隔离边界 | 每个沙箱一个 micro-VM | 每会话一个 VM 级隔离的沙箱（Learn） | 每个 Sandbox 一个 Kata pod VM | 每个会话一个 Kata pod VM | 每个沙箱一个 Firecracker micro-VM |
| VMM 和 hypervisor | API 返回 `vmm_type` <!--v:a.vmm.value-->cloudhypervisor<!--/v-->；文档没有写 hypervisor | 未公开；文档只说明 VM 级隔离 | Microsoft Hyper-V 上的 Cloud Hypervisor（Learn） | 与 C 相同 | Linux KVM（`/dev/kvm`）上的 <!--v:e.vmm.value-->firecracker<!--/v-->（<!--v:e.isolation.firecracker_version-->v1.14-0.2.0<!--/v-->），读自宿主机进程列表 |
| 读到的内核 | guest <!--v:a.isolation.guest_kernel-->6.12.8+<!--/v--> | 未暴露，无法读回 | pod <!--v:c.isolation.guest_kernel-->6.6.137.mshv1-1.azl3<!--/v-->，runc pod <!--v:c.isolation.system_node_kernel-->6.8.0-1067-azure<!--/v--> | Kata 节点池节点 <!--v:d.node_kernel.value-->6.6.137.mshv2-2.azl3<!--/v-->；未在会话 pod 内读取 | guest <!--v:e.isolation.guest_kernel-->6.1.177+<!--/v-->，宿主机 VM <!--v:e.isolation.host_kernel-->6.17.0-1022-azure<!--/v--> |
| 节点归谁 | 微软 | 微软 | 你 | 你 | 你 |

B 的“每会话一个、VM 级隔离”是 `SOURCE_FACT`，不是本地读回的 VMM 或内核结果。C 和 D 用的是同一个 Kata runtime class，所以隔离方式并不能区分它们，真正的区别在于由谁来运行平台。E 在你自己的 Azure Gen2 VM 内直接经 `/dev/kvm` 运行 Firecracker。

**按阶段拆细的秒数。** 如果把纯沙箱启动、外挂私有 Azure Blob 卷和第一轮 agent 回答揉成一个冷启动数字，A 会因为完整 workshop 配置同步挂载私有 Blob 卷（同一次归因实测里，挂卷时 create → Running <!--v:a.attr.vnetvolume.range-->15.79–25.12<!--/v--> s，不挂卷 <!--v:a.attr.small.range-->1.6–2.7<!--/v--> s）而显得很慢，但实际上 A 原生支持 `Memory` 内存快照，跨挂起保留会话状态并不需要外挂 Blob 卷。下面把每个阶段单独拆开。A 是 2026-10-18 不挂 Blob 卷的三次实测，加 2026-10-09 挂卷的三次实测和归因矩阵；B 是 2026-09-27 的一次实测、2026-10-15 的三次会话接口实测，以及 2026-10-18 的一轮 D 口径压测和空闲等待实测；C 是 2026-10-18 不挂卷和挂 Blob PVC 各三次实测，加 2026-09-27 的一次实测；D 是 2026-09-29 的一轮压测，加 2026-10-18 的三次会话接口实测；E 是 2026-10-17 用 `code-interpreter-v1` 做的一轮压测（更早用 `base` 模板的 2026-10-14 和 2026-10-15 实测见下方实测表）。A 和 C 使用 workshop reflection agent；B 使用 Agent Framework 和 ResponsesHostServer；D 使用私有预览 sample；E 使用 Foundry Prompt Agent，它的函数工具用 E2B 的 Code Interpreter 执行代码。它们使用同一个模型和有状态交互，但不是相同容器。B 的 2026-09-27 实测和 D 是从中国的一台笔记本经 Foundry 端点调用的（到 Azure 的往返时延 <!--v:d.client_rtt.range-->320–800<!--/v--> ms）；B 的 2026-10-15 会话实测从 Japan East 的一台 Windows VM 经 Azure API Management 网关调用，B 的 2026-10-18 实测也一样；D 的 2026-10-18 实测从同一台 VM 直接调用端点；E 的压测脚本直接在 East US 2 的 E2B 宿主 VM 上运行；A 的回答在沙箱内计时，C 在 2026-09-27 于它的 LoadBalancer 处计时，2026-10-18 在 pod 内计时。请把同一行作为现场记录来读，不要当作受控的产品基准测试：

**各路径启动计时定义、测试问题原文与可执行压测脚本。** 纯沙箱或 pod 启动耗时从发出 CLI/SDK 创建请求开始计时，到沙箱或 pod 状态变为就绪（`Running` / `Active` / `Ready`）为止，不含模型推理：

| 测试口径与覆盖路径 | 纯沙箱 / pod 就绪计时起点 → 终点 | 按顺序发送的测试问题原文 | 仓库内可执行压测脚本 |
|---|---|---|---|
| **有状态 Agent 与挂起/恢复（`A`、`B`、`C`、`E`）** | **A**：SDK `_do_create_sandbox` → `get_sandbox` 状态 `Running`<br>**B**：`POST .../endpoint/sessions` → `active`<br>**C**：`kubectl apply` / `operatingMode: Running` → Sandbox `Ready`<br>**E**：Code Interpreter 的 `Sandbox.create()`（模板 `code-interpreter-v1`）→ Firecracker `Running` | A、B、E 依次发送——第 `1` 轮：`"Where is Bangkok? Answer in one short sentence."`<br>第 `2` 轮（后续）：`"How many questions have I asked before this one? Number only."`<br>第 `3–4` 轮（挂起恢复后）：`"How many questions have I asked before this one? Number only."`<br>C：2026-10-18 发同样的第 `1`、`2` 轮；挂 Blob PVC 时，pod 丢失后发第 `3` 轮，挂起恢复后发第 `4` 轮；2026-09-27 没有保留请求原文 | [`tools/measure_aca.py`](tools/measure_aca.py)<br>[`tools/measure_sessions.py`](tools/measure_sessions.py)<br>[`tools/measure_c.py`](tools/measure_c.py)<br>[`tools/measure_e2b.py`](tools/measure_e2b.py)（`agent` 模式） |
| **Responses 冷启动、追问、并发与恢复（`B`、`D`、`E`；并发另含 `A`、`C`）** | **D**：Pod `creationTimestamp` → `Ready` 条件<br>**E**：Code Interpreter 的 `Sandbox.create()`（模板 `code-interpreter-v1`）→ Firecracker `Running` | **D**，以及 2026-10-18 的 **B** —— 冷启动（`n` 个新会话）：`"Reply with exactly COLD-{i}"`<br>同会话追问（`1` 个会话）：`"Remember the code word LANTERN-7. Reply only OK."` → `"What is the code word? Reply with the word only."` → `"Reply with exactly WARM-{i}"`<br>并发（`4` 和 `8` 并发）：`"Remember SCALE-{i}. Reply only OK."` → `"What did I ask you to remember? Word only."`；2026-10-18 **A** 和 **C** 并发时也发这两个问题<br>**E** —— 步骤相同，每个问题都让 agent 使用沙箱工具，例如 `"Use run_in_e2b_sandbox to print COLD-{i}, then reply with exactly COLD-{i}"`；全部问题见 [VALIDATION_CN.md](VALIDATION_CN.md#e-2026-10-17-ci-perfcode-interpreter-v1-的冷启动后续回答并发沙箱替换与空闲容量) | [`tools/measure_responses.py`](tools/measure_responses.py)<br>[`tools/measure_e2b.py`](tools/measure_e2b.py)（`perf` 模式） |

A 和 E（A 口径）的冷启动和恢复到回答采用分段相加，不是客户端连续端到端计时：SDK 创建或恢复的耗时，加上沙箱内计时的回答耗时（A）或 Prompt Agent 轮次耗时（E）。B 的会话接口冷启动同样是两次客户端请求相加：先创建会话，再取第一个回答；B 的 2026-09-27 实测用 `azd ai agent invoke`，没有保留请求原文。C 的冷启动同样是 apply 到 Ready 加第一个回答。每个总计都是先在每次实测内相加、再取中位数；它下面的子项行是各子项单独取的中位数，可能来自不同的实测，所以不一定加得起来；每次实测的分项见 [VALIDATION_CN.md](VALIDATION_CN.md#实测记录)。恢复从挂起完成后开始计时，不含停止和空闲等待。B 的后续回答行同时列出 2026-09-27 实测（gateway 模型路由）、2026-10-15 实测（direct 模型路由）和 2026-10-18 的 D 口径压测。每个计时的起点、终点和在哪里计时，见 [VALIDATION_CN.md](VALIDATION_CN.md#架构与指标口径)。

**这些秒数不能用来给五种产品做性能排名。** 各路径的计时位置、问题输入、reasoning 设置、输出 token 数、镜像缓存和样本量，并未统一控制或逐次完整记录。模型名相同不代表时延测试条件相同。数值合理性校验能拦住无效耗时，但不能证明产品性能，也不能补齐缺失的打点。

<!-- BEGIN GENERATED: comparison -->
| 实测或文档项 | A · ACA Sand&shy;boxes | B · Foundry hosted agent | C · AKS + agent-sandbox | D · BYO-AKS | E · E2B on Azure VM |
|---|---|---|---|---|---|
| **冷启动公式**<br>各项均为耗时，单位：秒。 | $T_{\mathrm{cold}}$<br>$= T_{\mathrm{ready}}$<br>$+ T_{\mathrm{first}}$<br><br>**Ready**：沙箱创建 → Running<br>**First**：首轮请求 → 回答，在沙箱内计时。<br>两段计时相加。 | $T_{\mathrm{cold}}$<br>$= T_{\mathrm{ready}}$<br>$+ T_{\mathrm{first}}$<br><br>**Ready**：创建会话 → `active`<br>**First**：就绪会话的首轮请求 → 回答。<br>两次客户端请求耗时相加。 | $T_{\mathrm{cold}}$<br>$= T_{\mathrm{ready}}$<br>$+ T_{\mathrm{first}}$<br><br>**Ready**：<code>kubectl </code><br><code>apply</code>&#8203; → Sandbox Ready，挂或不挂 Blob PVC。<br>**First**：首轮请求 → 回答，在 pod 内计时&#8203;（2026-09-27 在 Load&shy;Balancer 处计时）。<br>两段计时相加。 | $T_{\mathrm{cold}}$<br>$= T_{\mathrm{pod}}$<br>$+ T_{\mathrm{other}}$<br><br>**Cold**：客户端 POST → 完整响应。<br>**Pod**：pod 创建 → Ready。<br>**Other**：同次 Cold − Pod&#8203;（推导；含端点、会话和 agent 链路），不是独立计时的 Ready → 回答。 | $T_{\mathrm{cold}}$<br>$= T_{\mathrm{ready}}$<br>$+ T_{\mathrm{first}}$<br><br>**Ready**：E2B 沙箱创建 → Running&#8203;（<code>code-</code><br><code>interpreter-</code><br><code>v1</code>&#8203;）。<br>**First**：首轮 Prompt Agent 请求 → 回答；agent 的代码由 E2B Code Interpreter&#8203;（`run_code`）在该沙箱里执行。<br>两段计时相加&#8203;（A 口径）。 |
| **纯冷启动总计&#8203;（不挂外部卷）** | **4.86 s** 中位数&#8203;（4.35–&#8203;8.11；n=3），每次实测相加；镜像 + VNet + 端口，不挂卷&#8203;（2026-10-18） | **12.31 s** 中位数&#8203;（11.65–&#8203;12.36；n=3），每次实测相加；首次 <code>/</code><br><code>responses</code>&#8203; 自动建会话、一次请求完成：9.43 s&#8203;（gateway 模型路由）/ 5.29 s&#8203;（direct），各 n=1；2026-10-18 经网关、D 口径：中位数 11.03 s&#8203;（10.98–&#8203;11.57；n=5） | **24.27 s** 中位数&#8203;（23.82–&#8203;27.34；n=3），每次实测相加；回答在 pod 内计时 | **25.49 s** 中位数&#8203;（23.53–&#8203;26.7；n=5），经 Foundry 端点一次请求 | **3.93 s** 中位数&#8203;（3.36–&#8203;4.62；n=3），每次实测相加&#8203;（A 口径）；一次请求 中位数 3.35 s&#8203;（2.7–&#8203;5.66；n=5）&#8203;（D 口径） |
| └ 子项 1：沙箱、会话或 pod 就绪 | 中位数 1.35 s&#8203;（1.22–&#8203;2.15；n=3），镜像 + VNet + 端口；仅镜像 中位数 2.31 s&#8203;（1.6–&#8203;2.7；n=3）&#8203;（2026-10-09） | 中位数 6.69 s&#8203;（6.51–&#8203;6.87；n=3），<code>POST </code><br><code>.../</code><br><code>endpoint/</code><br><code>sessions</code>&#8203; → `active` | 中位数 16.45 s&#8203;（15.32–&#8203;18.9；n=3），<code>kubectl </code><br><code>apply</code>&#8203; → Sandbox Ready | 镜像已缓存 8–&#8203;10 s&#8203;（n=6）；新节点 25 s&#8203;（n=2） | agent 实测中 中位数 0.08 s&#8203;（0.07–&#8203;0.22；n=3）；D 口径新会话中 中位数 0.073 s&#8203;（0.069–&#8203;0.13；n=5） |
| └ 子项 2：就绪后 → 第一个回答 | 中位数 3.51 s&#8203;（3.13–&#8203;5.96；n=3），沙箱内计时；每次发请求时 agent 都已在监听 | 已就绪会话上 中位数 5.62 s&#8203;（4.79–&#8203;5.85；n=3）；其中服务端记录的生成时间 2–&#8203;4 s | 中位数 8.44 s&#8203;（7.82–&#8203;8.5；n=3），在 pod 内计时；在 Load&shy;Balancer 处计时 12.75 s&#8203;（2026-09-27，n=1） | 推导余量 中位数 15.49 s&#8203;（14.01–&#8203;16.16；n=3）：同次冷启动总耗时减 pod 创建 → Ready；不是独立计时的 Ready → 回答&#8203;（agent 轮次 2–&#8203;5 s） | 中位数 3.85 s&#8203;（3.14–&#8203;4.55；n=3）&#8203;（A 口径）；中位数 3.17 s&#8203;（2.5–&#8203;5.43；n=5）&#8203;（D 口径） |
| **带私有 Blob 卷的冷启动总计**<br>可选：想在挂起再恢复后保留数据，只有 C 必须挂卷 | **28.0 s** 中位数&#8203;（27.07–&#8203;50.41；n=3），SDK 创建 + 沙箱内回答，每次实测相加&#8203;（2026-10-09）；中位数那次：创建 24.12 s + 回答 3.88 s | 不需要：平台恢复 `$HOME` 和 `/files` | **必须挂卷**才能保留数据；**24.19 s** 中位数&#8203;（24.04–&#8203;26.68；n=3），每次实测相加；2026-09-27：57.65 s&#8203;（n=1；apply → Ready 44.9 s + 在 Load&shy;Balancer 处回答 12.75 s） | 不需要：`:stop` 前写入的文件会保留 | 不需要：模板和快照存在宿主 VM 的系统盘上 |
| └ 子项：挂卷附加耗时 | 同一次归因实测&#8203;（2026-10-09）里 create → Running：不挂卷 1.6–&#8203;2.7 s&#8203;（只加镜像、VNet 或端口；n=7），挂卷 15.79–&#8203;25.12 s&#8203;（镜像 + VNet + 卷；n=2） | 无 | 测不出差别：apply → Ready 挂 PVC 中位数 16.46 s&#8203;（16.26–&#8203;16.81；n=3），不挂 中位数 16.45 s&#8203;（15.32–&#8203;18.9；n=3） | 无 | 无 |
| **同一会话的后续回答** | 带 Blob 卷 中位数 1.05 s&#8203;（1.04–&#8203;1.54；n=3）；不挂卷 中位数 0.84 s&#8203;（0.67–&#8203;1.02；n=3）&#8203;（2026-10-18） | 4.03, 5.54 s&#8203;（n=2）&#8203;（<code>b-</code><br><code>2026-</code><br><code>09-</code><br><code>27</code>&#8203;，gateway 模型路由）；中位数 4.59 s&#8203;（4.42–&#8203;4.81；n=3）&#8203;（<code>b-</code><br><code>2026-</code><br><code>10-</code><br><code>15-</code><br><code>sessions</code>&#8203;，direct 模型路由）；中位数 3.94 s&#8203;（3.88–&#8203;4.08；n=3）&#8203;（<code>b-</code><br><code>2026-</code><br><code>10-</code><br><code>18-</code><br><code>perf</code>&#8203;，D 口径） | 中位数 1.03 s&#8203;（1.0–&#8203;1.08；n=3），在 pod 内计时；在 Load&shy;Balancer 处 1.96 s&#8203;（n=1）&#8203;（2026-09-27） | 中位数 12.9 s&#8203;（11.17–&#8203;16.42；n=3） | 中位数 4.09 s&#8203;（3.61–&#8203;4.17；n=3）&#8203;（A 口径）；中位数 3.93 s&#8203;（3.36–&#8203;4.59；n=3）&#8203;（D 口径） |
| **挂起 / 暂停与恢复就绪耗时** | 带 Blob 卷：停止 中位数 7.56 s&#8203;（5.97–&#8203;9.31；n=3），恢复 → Running 中位数 2.83 s&#8203;（1.61–&#8203;3.02；n=3）；不挂卷&#8203;（2026-10-18）：停止 中位数 10.67 s&#8203;（9.88–&#8203;20.23；n=3），恢复 → Running 中位数 1.22 s&#8203;（0.82–&#8203;4.46；n=3） | `:stop` → idle 中位数 3.05 s&#8203;（2.9–&#8203;7.71；n=3）；释放算力、保留 `$HOME`，无内存快照；下一次请求时唤醒&#8203;（见下一行） | 挂起 → pod 消失 中位数 9.24 s&#8203;（9.1–&#8203;9.45；n=3）；恢复 → Ready 中位数 15.93 s&#8203;（15.87–&#8203;17.28；n=3）；无内存快照 | `:stop` → idle 中位数 22.72 s&#8203;（19.54–&#8203;23.55；n=3）；会话 pod 结束，之前写入的文件保留，无内存快照；下一次请求时唤醒&#8203;（见下一行） | 暂停 中位数 0.09 s&#8203;（0.08–&#8203;0.29；n=3）；恢复 → Running 中位数 0.64 s&#8203;（0.63–&#8203;1.43；n=3） |
| **发起恢复 → 第一个回答&#8203;（不含停止）** | 带 Blob 卷 中位数 14.45 s&#8203;（12.44–&#8203;17.22；n=3）；不挂卷 中位数 2.96 s&#8203;（2.7–&#8203;6.78；n=3），对话接着继续 3/3&#8203;（2026-10-18）。中位数那次&#8203;（回答在沙箱内计时）：带卷 恢复 1.61 s + 回答 12.84 s，不挂卷 恢复 1.22 s + 回答 1.74 s | 中位数 12.02 s&#8203;（11.66–&#8203;12.35；n=3）：停止后同一会话的下一轮请求分到新算力并恢复 `$HOME`；停止前写入的文件读回 3/3，问题计数持续增长 3/3。17 分钟没有请求后，状态读到 `active` 1/3、`idle` 2/3，下一轮：中位数 12.67 s&#8203;（12.12–&#8203;12.71；n=3）；5 分钟后：中位数 5.16 s&#8203;（4.43–&#8203;5.76；n=3） | 中位数 23.34 s&#8203;（22.45–&#8203;24.23；n=3）：Running → Ready，再加 pod 内的回答；对话从 Blob PVC 接着继续 3/3 | 中位数 19.78 s&#8203;（19.14–&#8203;22.4；n=3）：停止后同一会话的下一轮请求启动新 pod；文件读回 3/3，问题计数持续增长 3/3 | 中位数 5.28 s&#8203;（4.96–&#8203;6.2；n=3）；恢复本身另行统计的中位数 0.64 s |
| **pod 或沙箱丢失 → 重新就绪** | 无法从外部制造：没有注入宿主机故障的接口，删除沙箱即结束会话 | 无法从外部制造：没有只杀掉会话沙箱的接口；显式停止与恢复见上方 | 中位数 24.79 s&#8203;（23.25–&#8203;25.24；n=3）；对话从 Blob PVC 接着继续 3/3&#8203;（2026-09-27：23.4 s，n=1） | 23.9 s&#8203;（n=1）；未测试被删会话的连续性 | 0.12 s&#8203;（n=1）；另一个存活会话在 6.86 s 内回答 |
| **空闲策略&#8203;（官方说明）** | [官网](https://learn.microsoft.com/azure/container-apps/sandboxes-overview#lifecycle-states)：可配置空闲自动挂起；可选 Memory 或 Disk 快照模式 | [官网](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents#sessions)：空闲超时 2–&#8203;60 min&#8203;（默认 15）后释放算力，保留 $HOME 和 /files；30 天不活跃后删除会话 | [官方 API](https://github.com/kubernetes-sigs/agent-sandbox/blob/v0.5.2/docs/api.md)：shutdown&shy;Time 是定时到期回收，不是按请求检测空闲；空闲回收需自行实现 | 未找到可核实的官方公开空闲策略；须向产品组确认 | [E2B 文档](https://e2b.dev/docs/sandbox)：按沙箱设置超时&#8203;（默认 5 min），支持显式 <code>beta_</code><br><code>pause</code>&#8203; / `connect` |
| **容量** | 无服务器；默认 500 并发活跃核&#8203;（标准上限 2000，本订阅实查 20000）及 3000 请求/分钟&#8203;（[文档](https://sandboxes.azure.com/docs/sandboxes/limits)）；已停止的沙箱不计入；2026-10-18：同时创建 4 个和 8 个完整规格沙箱，分别回答 4/4 和 8/8 | 每个会话一个 VM 隔离的沙箱，按会话扩缩，没有副本数或预热池可配置&#8203;（[文档](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents#scaling-and-right-sizing)）；单会话最高 20 GiB 磁盘&#8203;（系统预留 20%），单个上传文件最大 50 MB；2026-10-18：同时开 4 个和 8 个新会话，分别回答 4/4 和 8/8 | 你的 Kata 节点池；2026-10-18 在 <code>Standard_</code><br><code>D4s_</code><br><code>v3</code>&#8203; 节点上：4 并发 4/4，8 并发 8/8：6 个在原有节点上，2 个在集群自动扩缩容新加的第二个节点上 | 单个 Standard_&#8203;D4s_&#8203;v5 节点观察到最多 5 个会话；3 个节点共 12 个；<code>500 </code><br><code>session_</code><br><code>creation_</code><br><code>failed</code>&#8203;、<code>429 </code><br><code>aks_</code><br><code>quota_</code><br><code>exceeded</code>&#8203; | 每套安装只有一台机器，这是设计如此&#8203;（[E2B](https://github.com/e2b-dev/runtime/blob/588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/README.md#when-one-node-is-not-enough)）；2026-10-17 在 1 台 <code>HUGEPAGES=4096</code>&#8203; 的 Standard_&#8203;D4ds_&#8203;v7 VM 上：4 并发 3/4、8 并发 3/8 回答，其余被拒&#8203;（<code>Failed </code><br><code>to </code><br><code>place </code><br><code>sandbox</code>&#8203;）；空闲的 <code>code-</code><br><code>interpreter-</code><br><code>v1</code>&#8203; 沙箱&#8203;（2 vCPU、2 GiB）：4096 页时 3 个，Compose 默认的 2048 页时 1 个&#8203;（512 MB 的 `base`：15 和 7 个）；第二台独立主机带来它自己的大页池&#8203;（<code>e-</code><br><code>2026-</code><br><code>10-</code><br><code>15-</code><br><code>multi</code>&#8203;，`base`：两台 14/16） |
| **本次路径部署耗时** | 146.6 s&#8203;（sandbox group、VNet 连接、磁盘镜像、卷、沙箱） | 161 s&#8203;（<code>azd </code><br><code>deploy</code>&#8203;；模型路由：gateway&#8203;（APIM）&#8203;） | 812.9 s&#8203;（准备脚本、私有链接、apply） | 854 s&#8203;（角色、<code>azd </code><br><code>provision</code>&#8203;、<code>azd </code><br><code>deploy</code>&#8203;；作者控制台记录，原始输出未保留） | 177 s&#8203;（2026-10-14：Docker Engine 33.0 s + E2B Compose 与 base 模板 144 s）+ 构建 <code>code-</code><br><code>interpreter-</code><br><code>v1</code>&#8203; 426 s&#8203;（2026-10-15，调大三项宿主机默认值后的第 4 次尝试） |

**本地配置与观察，不是官网空闲策略：** A 本次使用 Memory 模式，自动挂起设置为 900 s。D 最早的 pod 在创建至少 87 min 后仍为 Running；这是 pod 的年龄，不是空闲时长或回收超时。B 的会话在 17 分钟没有请求后状态读到 `active` 1/3、`idle` 2/3（2026-10-18）。
<!-- END GENERATED: comparison -->

值得注意的几点：
- **不挂私有 Blob 卷时，A 很快，会话靠 Memory 快照就能保住：** 只用镜像、VNet 和端口、不挂卷（2026-10-18），新沙箱给出第一个回答的冷启动中位数 <!--v:a.nv.cold.median-->4.86<!--/v--> s（<!--v:a.nv.cold.range-->4.35–8.11<!--/v--> s，n=<!--v:a.nv.cold.n-->3<!--/v-->；中位数那次：创建 <!--v:a.nv.cold_mid.create-->1.35<!--/v--> s + 沙箱内的第一个回答 <!--v:a.nv.cold_mid.answer-->3.51<!--/v--> s）；停止再恢复后，对话接着继续 <!--v:a.nv.state_kept.count-->3<!--/v-->/<!--v:a.nv.state_kept.n-->3<!--/v--> 次，发起恢复后中位数 <!--v:a.nv.recover.median-->2.96<!--/v--> s 给出回答。workshop 配置里的私有 Blob 卷是可选项；挂卷时（2026-10-09）冷启动中位数 <!--v:a.cold.median-->28.0<!--/v--> s（中位数那次：创建 <!--v:a.cold_mid.create-->24.12<!--/v--> s + 回答 <!--v:a.cold_mid.answer-->3.88<!--/v--> s），恢复到回答 <!--v:a.recover.median-->14.45<!--/v--> s（中位数那次：恢复 <!--v:a.recover_mid.resume-->1.61<!--/v--> s + 回答 <!--v:a.recover_mid.answer-->12.84<!--/v--> s）。同一会话的后续回答两种情况都在约 1 s（带卷 <!--v:a.warm.median-->1.05<!--/v--> s，不挂卷 <!--v:a.nv.warm.median-->0.84<!--/v--> s），与 C 相当（<!--v:c.n.warm.median-->1.03<!--/v--> s）；它们都在沙箱或 pod 内计时，不含网络。所以只为跨挂起保留会话，A 不需要外挂卷；但这时状态只存在这个沙箱里（删除沙箱后、或从别的沙箱读取状态，都没有测）。
- **E（E2B on Azure VM）用 E2B 的 Code Interpreter 在 2 GiB 的 Firecracker 沙箱里执行 agent 的代码，沙箱创建不到 0.1 s；能同时放几个由 VM 的大页池决定：** 使用 `code-interpreter-v1` 时，agent 实测中沙箱创建中位数为 <!--v:e.ci.create.median-->0.08<!--/v--> s，暂停 <!--v:e.ci.pause.median-->0.09<!--/v--> s，恢复 <!--v:e.ci.resume.median-->0.64<!--/v--> s，新会话的回答中位数为 <!--v:e.ci.d_cold.median-->3.35<!--/v--> s。决定能放几个的是大页池而不是 CPU：一台 `HUGEPAGES=4096`（8 GiB）的 `Standard_D4ds_v7` 能放 <!--v:e.ci.idle.ci_4096-->3<!--/v--> 个空闲的 `code-interpreter-v1` 沙箱（空闲页数 ÷ 每个 2 GiB 沙箱的 1024 页），8 个会话同时进行时回答 <!--v:e.ci.c8.answered-->3<!--/v-->/8，其余被拒；同样的大页池能放 <!--v:e.ci.idle.base_4096-->15<!--/v--> 个 2026-10-14 和 2026-10-15 实测所用的 512 MB `base` 沙箱。构建这个模板要调大三项宿主机默认值（大页池、构建工作空间、128 GB 系统盘）。Embed 按设计只有一台机器：VM 操作系统、Docker Compose 栈、网络安全规则、大页大小，以及把会话分到多台 VM，都要你自己负责；暂停的沙箱只能在暂停它的那台 VM 上恢复。
- **D（BYO-AKS）当前处于私有预览阶段，重在验证产品形态，性能收敛计划在公开预览阶段完成：** 在当前预览 build 中，会话 pod 在 <!--v:d.pod_ready.range-->8–10<!--/v--> s 内就绪，而端到端范围是 <!--v:d.cold.range-->23.53–26.7<!--/v--> s（pod Ready 后到首答中位数 <!--v:d.first_after_ready.median-->15.49<!--/v--> s）；同一台笔记本直接调用同一个模型的中位数是 <!--v:d.model_direct.median-->2.69<!--/v--> s（low reasoning effort；该直连基线不是与 agent 配置完全匹配的基准测试）。没有打点的剩余时间只能统称为端点、会话和 agent 链路，不能当成已测出的网关内部耗时。按产品组说明，现阶段 Private Preview 主要用于展示和验证「Foundry 控制面 + 客户自有 AKS Kata 节点池」的产品形态，性能问题计划在 Public Preview 阶段解决，目前的目标是至少达到与全托管 Foundry（方案 B）同一水平线上。
- **2026-10-18 的补测补上了 B、C、D 的空白：** C 不挂外部卷时回答中位数 <!--v:c.n.cold.median-->24.27<!--/v--> s（apply → Ready <!--v:c.n.apply_ready.median-->16.45<!--/v--> s，加 pod 内的第一个回答）；已绑定的 Blob PVC 测不出额外耗时（apply → Ready <!--v:c.p.apply_ready.median-->16.46<!--/v--> s），pod 丢失和挂起/恢复后对话都接着保留，<!--v:c.p.state_kept.count-->3<!--/v-->/<!--v:c.p.state_kept.n-->3<!--/v--> 次。D 的会话接口能在你的集群上停止和恢复会话：`:stop` → idle <!--v:d.sess.stop.median-->22.72<!--/v--> s，下一轮 <!--v:d.sess.resume.median-->19.78<!--/v--> s，跑在新的会话 pod 上，文件保留。A、B、C 同时开 8 个新会话都能回答；C 的最后 <!--v:c.c8.on_new_nodes-->2<!--/v--> 个等集群自动扩缩容加出第二个节点。在 B 上，17 分钟没有请求后的下一轮中位数 <!--v:b.idle.next.median-->12.67<!--/v--> s，和显式 `:stop` 之后的恢复差不多（<!--v:b.sess.resume.median-->12.02<!--/v--> s，2026-10-15），5 分钟后只要 <!--v:b.idle5.next.median-->5.16<!--/v--> s：与平台在 15 分钟的默认空闲超时之后释放会话算力一致，即使有一次状态仍读到 `active`。
- 在本次观察到的 D 预览 build 里，应保守地按“开过的会话数”而不只是“正在执行的请求数”规划容量；pod 年龄的观察不能证明空闲回收超时。

**每次实测。** 按 A→B→C→D→E 分组，同一路径内按日期从早到晚排列，与 [VALIDATION_CN.md](VALIDATION_CN.md) 的顺序一致；该页记录每次实测的输入、过程、结果和边界：

<!-- BEGIN GENERATED: runs -->
| 实测 | 路径 | 场景 | 结果 |
|---|---|---|---|
| `a-2026-09-27-setup` | A | 首次部署，请求唤醒 | 部署 146.6 s；向已停止的沙箱发请求，23.7 s 后回答；内核 `6.12.8+` |
| `a-2026-10-09-agent` | A | 完整 agent，跑 3 次 | 冷启动 28.0 s、后续 1.05 s、恢复到回答 14.45 s（中位数）；3/3 次 vmm 为 `cloudhypervisor`；历史持续增长 3/3 |
| `a-2026-10-09-attribution` | A | 按配置拆分创建耗时 | 只加镜像、VNet 或端口 1.6–2.7 s；加私有 Blob 卷后 15.79–25.12 s |
| `a-2026-10-09-late-mount` | A | 先启动、后挂 Blob | 启动 3.99–7.2 s，再挂载 12.4–20.29 s（n=2） |
| `a-2026-10-18-scale` | A | 同时创建 4 个和 8 个 agent 沙箱 | 4 并发 4/4、8 并发 8/8 回答；创建 → Running 15.49–24.55 s；无遗留 |
| `a-2026-10-18-novolume` | A | 不挂 Blob 卷的完整 agent，跑 3 次 | 冷启动 4.86 s、后续 0.84 s、恢复到回答 2.96 s（中位数）；停止和恢复后对话接着继续 3/3；无遗留 |
| `b-2026-09-27` | B | 部署、新会话、后续回答；gateway 模型路由 | 部署 161 s；新会话 9.43 s；后续 4.03, 5.54 s |
| `b-2026-10-15-sessions` | B | 显式会话生命周期，跑 3 次 | 创建 → active 6.69 s、第一个回答 5.62 s、后续 4.59 s、停止 → idle 3.05 s、恢复到回答 12.02 s（中位数）；文件保留 3/3 |
| `b-2026-10-18-perf` | B | 经网关跑 D 口径：冷启动、后续、4 和 8 并发 | 冷启动 11.03 s、后续 3.94 s（中位数）；4 并发 4/4、8 并发 8/8 回答 |
| `b-2026-10-18-idle` | B | 17 分钟没有请求后的下一轮，以及 5 分钟后的对照；各跑 3 次 | 17 分钟后状态 `active` 1/3、`idle` 2/3；下一轮 12.67 s，等待前的后续 3.81 s，5 分钟后 5.16 s（中位数）；文件保留 3/3 |
| `c-2026-09-27` | C | Kata Sandbox、pod 丢失、挂起/恢复 | pod 内核 `6.6.137.mshv1-1.azl3`，Ubuntu 系统节点池的 runc pod 内核 `6.8.0-1067-azure`；pod 丢失后 23.4 s 就绪；恢复到回答 34.2 s |
| `c-2026-10-18-perf` | C | 不挂卷和挂 Blob PVC 的冷启动、pod 丢失、挂起/恢复、4 和 8 并发 | 冷启动不挂卷 24.27 s、挂 PVC 24.19 s；pod 丢失 → Ready 24.79 s；恢复到回答 23.34 s（中位数）；4 并发 4/4、8 并发 8/8 回答 |
| `d-2026-09-29-placement` | D | 会话跑在哪里 | 加 NSG 规则 `Allow-AzureCloud-FoundryRouter-443` 后，每个会话 pod 都是 `kata-vm-isolation`，跑在你的节点池上 |
| `d-2026-09-29-perf` | D | 冷启动、后续、4 和 8 并发 | 冷启动 25.49 s、后续 12.9 s（中位数）；4 并发 0/4、8 并发 2/8 回答（节点池已满） |
| `d-2026-09-29-recovery` | D | 删除一个会话 pod | 23.9 s 后替代 pod 就绪；另一个存活会话在 14.8 s 内回答；未测试被删会话的连续性 |
| `d-2026-10-18-sessions` | D | 显式会话生命周期，跑 3 次 | 创建 → active 9.32 s、第一个回答 11.01 s、停止 → idle 22.72 s、恢复到回答 19.78 s（中位数）；文件保留 3/3；每次停止后换一个新的会话 pod |
| `e-2026-10-14-agent` | E | Prompt Agent + E2B，跑 3 次 + 20 次微基准 | 创建 0.07 s（本机 0.051–0.089 s）、冷启动 4.26 s、后续 2.95 s、恢复到回答 6.48 s（中位数）；宿主机进程列表里的 VMM 为 `firecracker`；历史持续增长 3/3 |
| `e-2026-10-14-perf` | E | 冷启动、后续、4 和 8 并发、沙箱替换 | 冷启动 3.6 s、后续 3.39 s（中位数）；4 并发 4/4、8 并发 8/8 回答；0.1 s 后替代沙箱就绪 |
| `e-2026-10-15-latest` | E | 最新 SDK；E2B 官方 code-interpreter 模板 | e2b 2.56.0：历史持续增长 3/3，创建 0.06 s、恢复 0.08 s（中位数）；code-interpreter 调大三项宿主机默认值后才建成；11 项检查中 10 项在 4/4 次都通过，JavaScript 每次都失败 |
| `e-2026-10-15-multi` | E | 两台独立 E2B 主机：第二台、并发、空闲容量、停一台 | host b：历史持续增长 3/3，创建 0.06 s；并发：单台 7/8，两台 14/16；停掉 host a 的 E2B 后，host b 照常服务，host a 上暂停的沙箱在 host b 上恢复不了 |
| `e-2026-10-17-ci-agent` | E | E2B Code Interpreter（`run_code`）跑在 `code-interpreter-v1` 里，跑 3 次；在 host c 上构建模板 | 创建 0.08 s、冷启动 3.93 s、后续 4.09 s、暂停 0.09 s、恢复 0.64 s、恢复到回答 5.28 s（中位数）；历史持续增长 3/3；模板在 3 次尝试中的第 3 次建成 |
| `e-2026-10-17-ci-perf` | E | 冷启动、后续、4 和 8 并发、沙箱替换、空闲容量；`code-interpreter-v1` | 冷启动 3.35 s、后续 3.93 s（中位数）；4 并发 3/4、8 并发 3/8 回答（大页池已满）；0.12 s 后替代沙箱就绪；`HUGEPAGES=4096` 时空闲可放 3 个 `code-interpreter-v1` 或 15 个 `base` 沙箱 |
<!-- END GENERATED: runs -->

**边界。**
- 只测了一个区域（East US 2）。A 的完整 agent 时延带 Blob 卷 n=3、不挂卷 n=3，另有同时 4 个和 8 个沙箱各一次；B 是一轮端到端实测、三次会话接口实测、一轮 D 口径压测（冷启动 n=5、后续回答 n=3、4 和 8 并发），以及两种空闲等待后各三次；C 是一轮端到端实测，加不挂卷和挂 Blob PVC 各三次（含 pod 丢失和挂起/恢复），以及 4 和 8 并发各一次；D 是一轮压测，其中镜像已缓存的冷启动 n=5、后续回答 n=3，会话落地和恢复各一次，另有三次会话接口实测；E 的对比列是 2026-10-17 在单台 `Standard_D4ds_v7` VM 上用 `code-interpreter-v1` 做的一轮压测：A 口径 n=3，D 口径冷启动 n=5、后续回答 n=3，并发 4 和 8，一次沙箱替换，以及两种大页池下的空闲容量；实测表里还有 2026-10-14 用 `base` 模板的一轮压测（含本机微基准 n=20）和 2026-10-15 的补测：第二台 VM 上的 A 口径 n=3，单台和两台上同时 8 个和 16 个会话，空闲容量 n=3，停一台一次，最新 SDK n=3，以及 E2B code-interpreter 检查 n=4。在依赖某个数字之前，请按 VALIDATION_CN 中的在线测量命令重新测。
- 这些是实施过程中的观察，不是产品基准测试，也不是 SLA。文档说 A 可以从预热池实现亚秒级启动；我们带私有 Blob 卷的完整配置没有达到；不挂卷时创建中位数为 <!--v:a.nv.create.median-->1.35<!--/v--> s（仅镜像为 <!--v:a.attr.image.median-->2.31<!--/v--> s）。
- D 是处于功能形态验证阶段的私有预览，它的行为（会话落地、空闲回收、各项限制以及公开预览优化前的时延）可能变化，接入需要产品组的示例和开通。
- 没有测的：B 的平台何时回收空闲会话（只在等待结束后读了一次状态），A 和 B 的 pod 或宿主机丢失（两个服务都没有注入这种故障的接口），由 Foundry 治理的 agent 按任务调用 ACA 沙箱（微软在 GA 后介绍的模式），E2B 的多节点方案 Bring Your Own Cloud 和 private cloud，官方 Azure Terraform 模块用新盘替换实例（我们订阅的存储账户策略阻止了部署），以及整台 E2B VM 或其磁盘丢失。
- 成本：D 的两节点保底费用为两个 `Standard_D4s_v5` 节点加 AKS Standard 层 <!--v:d.cost_floor.value-->0.484<!--/v--> USD/h；E 的单 VM 保底费用为一台 `Standard_D4ds_v7` VM、一个 Standard 静态公网 IP 加一块 50 GB Premium SSD P6 磁盘，按 East US 2 零售价为 <!--v:e.cost_floor.value-->0.344<!--/v--> USD/h。构建 `code-interpreter-v1` 需要比 50 GB 更大的系统盘（我们用的是 128 GB），费用更高，上面的价格没有算进去。请按你自己的价格核算。

## 操作步骤

**先部署，再使用 agent。** 主线按[同事的固定版本 workshop](https://github.com/oxcp/ainotes/tree/905f2c2/agenthost)组织：创建共享底座 → 部署所选方案 → 打开或调用应用。压测和历史结果重算是可选项，不属于部署步骤。

**执行边界：** 原始部署产生了仓库保留的历史结果，但下面这套参数化步骤尚未在全新订阅逐条重跑。D 还依赖产品组的私有示例和开通；离线 CI 不能证明云端部署成功。

| 顺序 | 在哪里 | 做什么 | 入口 |
|---|---|---|---|
| 1 | 工作站 | 克隆、填写配置、登录 | `config/.env.example` |
| 2 | Azure 订阅 | 创建共享底座 | workshop `module-01/setup.sh` |
| 3 | C | 构建镜像、创建 AKS、部署 Sandbox 并打开应用 | workshop `module-03` |
| 4 | A | 创建 sandbox group 并部署 agent 沙箱 | workshop `module-04` + `tools/aca_sandbox.py` |
| 5 | B | 部署 hosted agent 并调用 | workshop `module-02` |
| 6 | D | 绑定现有 AKS，部署并调用私有预览 agent | 产品组示例 |
| 7 | E | 在 Azure Gen2 VM 上部署 E2B Embed，构建 E2B 的 Code Interpreter 模板，并由 Foundry Prompt Agent 调用 | `e2b-dev/runtime` + `e2b-dev/code-interpreter` |

**A = ACA Sandboxes，B = Foundry hosted agent，C = AKS + agent-sandbox，D = BYO-AKS，E = E2B on Azure VM**。上游把 module-02 叫 Solution A、module-03 叫 Solution B、module-04 叫 Solution C；看它时以模块编号为准。只执行所选方案：B 的前置是第 1–2 步；这里 A 的完整示例复用第 3 步创建的镜像和网络，但 ACA 产品本身不依赖 AKS。D 使用已有集群和单独开通的示例，本页不会自动替你新建 D 的集群。E 在单台开启嵌套虚拟化的 Azure VM 上运行开源 E2B Embed Docker Compose 栈。

**前提。** Bash、Git、curl、带 venv 模块的 Python 3.10+（Ubuntu/Debian 需安装 `python3-venv`）、Azure CLI 2.80+、kubectl、azd 1.34+；执行 `azd ext install microsoft.foundry` 安装扩展。订阅权限需 Owner，或 Contributor 加 Role Based Access Control Administrator，所选区域需有模型配额。部署 A 时，你的身份还需要 `Container Apps SandboxGroup Data Owner` 角色（[Learn](https://learn.microsoft.com/azure/container-apps/sandboxes-overview#prerequisites)）；workshop 的 `sandbox-deploy.sh` 能识别当前登录用户时会自动分配，识别不了只打印警告。使用非生产订阅。C 需要填写实际公网出口 CIDR；这个 HTTP workshop 应用不是生产级 HTTPS/登录部署。

**1. 克隆并填写配置。** 克隆到新目录后编辑 `.env`：填写 `SUBSCRIPTION_ID`、`LOCATION`、`RESOURCE_GROUP`；部署 C 时填写 `C_ALLOW_CIDR`。`SN` 在第 2 步拿到后再填。

```bash
git clone --filter=blob:none https://github.com/xinyuwei-david/Azure-Agent-Sandbox-Hosting.git
cd Azure-Agent-Sandbox-Hosting
export HOSTING_REPO="$PWD"
git clone https://github.com/oxcp/ainotes.git "$HOME/ainotes"
git -C "$HOME/ainotes" checkout 905f2c2
cp config/.env.example .env
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

编辑完成后登录，运行上游前置检查。工具、权限或配额未满足时先解决，不要继续创建资源。后续都在这个 shell 中操作：它保存着用来回到本仓库的 `HOSTING_REPO`，以及已激活的 `.venv`。

```bash
az login
set -a && . "$HOSTING_REPO/.env" && set +a
az account set --subscription "$SUBSCRIPTION_ID"
(cd "$WORKSHOP_DIR/agenthost" && chmod +x check-prerequisites.sh && ./check-prerequisites.sh)
```

**2. 创建共享底座。** [Module 1](https://github.com/oxcp/ainotes/blob/905f2c2/agenthost/module-01/README.md)创建 Foundry 项目和模型、APIM、ACR、Storage 与托管身份。

```bash
(cd "$WORKSHOP_DIR/agenthost/module-01" && chmod +x setup.sh && ./setup.sh)
az group show -g "$RESOURCE_GROUP" --query tags.deploymentSN -o tsv
```

成功标志：脚本输出 `Template deployed successfully.`，第二条命令返回非空后缀。把后缀填到 `.env` 的 `SN`，重新加载，让所有派生资源名一起更新；不能保留 `YOUR-DEPLOYMENT-SUFFIX` 继续执行。

```bash
set -a && . "$HOSTING_REPO/.env" && set +a
```

**3. C — 部署 AKS 上的应用。** 按 [Module 3](https://github.com/oxcp/ainotes/blob/905f2c2/agenthost/module-03/README.md)执行。准备脚本创建 AKS/Kata、控制器、镜像和 PVC，并不部署应用；后面的 `kubectl apply` 才创建 Sandbox 和 Service。

```bash
cd "$WORKSHOP_DIR/agenthost/module-03"
chmod +x prepare-agent-sandbox.sh deploy-storage-private-link.sh
./prepare-agent-sandbox.sh
if [ "$(az storage account show -g "$RESOURCE_GROUP" -n "$ACA_STORAGE_ACCOUNT" --query publicNetworkAccess -o tsv)" = "Disabled" ]; then
  ./deploy-storage-private-link.sh
fi
kubectl apply -f agent-sandbox.yaml
kubectl wait sandbox agent-host -n "$NAMESPACE" --for=condition=Ready --timeout=5m
```

成功标志：Sandbox 到达 `Ready`。接下来只允许配置的出口 CIDR，取出真正的应用地址并发起请求：

```bash
if [ -z "$C_ALLOW_CIDR" ] || [[ "$C_ALLOW_CIDR" == YOUR-* ]]; then
  echo "C_ALLOW_CIDR is not set: put your public egress CIDR in .env, reload it and run this block again" >&2
else
  kubectl patch service agent-host-lb -n "$NAMESPACE" --type merge \
    -p "{\"spec\":{\"loadBalancerSourceRanges\":[\"$C_ALLOW_CIDR\"]}}"
  kubectl wait service agent-host-lb -n "$NAMESPACE" --for=jsonpath='{.status.loadBalancer.ingress[0].ip}' --timeout=5m
  C_AGENT_HOST=$(kubectl get service agent-host-lb -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
  C_AGENT_URL="http://${C_AGENT_HOST}"
  printf 'C application: %s\n' "$C_AGENT_URL"
  curl --fail-with-body --show-error --max-time 30 "$C_AGENT_URL/ready"
  curl --fail-with-body --show-error --max-time 180 \
    -H 'Content-Type: application/json' \
    -d '{"query":"Where is Bangkok? Answer in one short sentence."}' "$C_AGENT_URL/reflect" | \
    python -c 'import json,sys; body=json.load(sys.stdin); answer=body.get("response"); print(json.dumps(body,ensure_ascii=False)); sys.exit(0 if isinstance(answer,str) and answer.strip() else "C invocation failed: non-empty response missing")'
fi
cd "$HOSTING_REPO"
```

如果第一行打印了 `C_ALLOW_CIDR` 的提示，说明后面的命令都没有执行：填好它，重新加载 `.env`，再运行一次这段命令。
浏览器打开打印出的地址即可使用聊天页面。`/ready` 应成功，`/reflect` 应返回非空 `response`；pod Ready 不等于应用已能回答。失败时在 `NAMESPACE` 查看 `kubectl get pods`、`kubectl describe pod`、`kubectl logs`；HTTP 不通还要检查出口 CIDR、Service 地址和网络规则。

**4. A — 部署 ACA 沙箱里的 agent。** [Module 4](https://github.com/oxcp/ainotes/blob/905f2c2/agenthost/module-04/README.md)创建 sandbox group；磁盘镜像和沙箱需要继续创建。下方 SDK 命令实际执行这些操作，不是重放测量记录。这里的完整示例复用第 3 步的镜像和网络；`ACA_SUBNET_PREFIX` 必须是该 VNet 内尚未占用的地址段。按 workshop 的做法，`aca-subnet` 建在 AKS 节点资源组的 VNet 里；[AKS 文档](https://learn.microsoft.com/azure/aks/faq)说明修改该资源组内的资源不受支持，删除集群时这个资源组也会一起删除。这只是 workshop 的简便做法；正式环境请在你自己管理的 VNet 里为 sandbox group 准备委派子网。

```bash
(cd "$WORKSHOP_DIR/agenthost/module-04" && chmod +x sandbox-deploy.sh && ./sandbox-deploy.sh)
NODE_RG=$(az aks show -g "$RESOURCE_GROUP" -n "$AKS_NAME" --query nodeResourceGroup -o tsv)
VNET=$(az network vnet list -g "$NODE_RG" --query "[0].name" -o tsv)
az network vnet subnet create -g "$NODE_RG" --vnet-name "$VNET" -n aca-subnet \
  --address-prefixes "$ACA_SUBNET_PREFIX" --delegations Microsoft.App/environments --query id -o tsv
```

把打印出的子网 ID 填到 `.env` 的 `ACA_SUBNET_ID`，再回本仓库执行：

```bash
cd "$HOSTING_REPO"
set -a && . ./.env && set +a
python tools/aca_sandbox.py vnet
python tools/aca_sandbox.py image
python tools/aca_sandbox.py volume
python tools/aca_sandbox.py create
python tools/aca_sandbox.py ask "Where is Bangkok? Answer in one short sentence."
```

成功标志：`create` 返回 Running，`ask` 返回真实回答。这里通过沙箱 exec 调用应用，不代表浏览器入口已开放；需要浏览器入口时按 Module 4 配置端口和 IP。缺配置先补齐再重试；镜像访问失败检查 ACR 权限，私有 Blob 访问依赖 VNet 和私有终结点。

**5. B — 部署并调用 hosted agent。** 在源代码克隆目录之外的新工作目录执行 [Module 2](https://github.com/oxcp/ainotes/blob/905f2c2/agenthost/module-02/README.md)。绑定已有项目后直接部署，B 不执行 `azd provision`。

```bash
mkdir -p "$HOME/workshop-b" && cd "$HOME/workshop-b"
azd auth login
azd ai agent init -m "$WORKSHOP_DIR/agenthost/module-02/azure.yaml" --project-id "$PROJECT_ID"
cd maf-agent
sed -i "s/<SN>/$SN/g" azure.yaml
azd env set AZURE_SUBSCRIPTION_ID "$SUBSCRIPTION_ID"
azd env set AZURE_LOCATION "$LOCATION"
azd env set AZURE_RESOURCE_GROUP "$RESOURCE_GROUP"
azd env set AZURE_AI_PROJECT_ID "$PROJECT_ID"
azd env set FOUNDRY_PROJECT_ENDPOINT "$PROJECT_ENDPOINT"
azd env set AI_MODEL_DEPLOYMENT_NAME gpt-5.4-mini
azd env set AZURE_TENANT_ID "$(az account show --query tenantId -o tsv)"
azd deploy
azd ai agent invoke "Hi"
azd ai agent show
cd "$HOSTING_REPO"
```

成功标志：部署结束且 `invoke` 返回真实回答。`show` 提供已部署的端点，可供 API 客户端调用，也可进入 Foundry agent playground 使用。默认保持 gateway 路由；只有明确需要时才改变。若部署一直 creating，查看 `azd ai agent monitor` 和门户状态，不能把超时当成功，也不要自动删除 agent。

**6. D — 私有预览部署。** 没有产品组示例和订阅开通就不能执行这条路径。先填写 `.env` 的 BYOAKS 配置，包括 `BYOAKS_SAMPLE_DIR`，并按示例当前指南配置 `AKS_RESOURCE_ID`、`HOSTING_IDENTITY_RESOURCE_ID`、`WORKLOAD_IDENTITY_RESOURCE_ID`、`STORAGE_ACCOUNT_RESOURCE_ID`、`ACR_RESOURCE_ID`、`APPLICATIONINSIGHTS_RESOURCE_ID`。只有功能标志 Registered 不代表已开通。

**D1. 准备现有集群的 Kata 节点池。** 先确认该节点 SKU 在订阅和区域可用，并符合当前开通要求；已有同名节点池时不要重复创建。

```bash
az aks nodepool add -g "$BYOAKS_RESOURCE_GROUP" --cluster-name "$BYOAKS_CLUSTER" -n "$BYOAKS_KATA_POOL" \
  --os-sku AzureLinux --workload-runtime KataVmIsolation --node-vm-size "$BYOAKS_KATA_VM_SIZE" --node-count 1
```

**D2. 在已配置的示例目录执行绑定。** 成功条件是 provision 完成、foundry-system 组件就绪，不是 pod 数量等于某个历史值。

```bash
cd "$BYOAKS_SAMPLE_DIR"
azd config set auth.useAzCliAuth true
azd auth login
azd provision
az aks get-credentials -g "$BYOAKS_RESOURCE_GROUP" -n "$BYOAKS_CLUSTER" --overwrite-existing
kubectl get pods -n foundry-system
```

**D3. 仅在需要时配置 router 网络路径。** 下方子网 NSG 规则是保留的 workshop 接法，不是通用生产规则。只有产品组确认该入口和来源适用于当前预览版本、且子网 NSG 阻断此路径时才执行；否则采用获准的网络配置。

```bash
ROUTER_IP=$(kubectl get svc foundry-router -n foundry-system -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
if [ -z "$ROUTER_IP" ]; then
  echo "foundry-router has no LoadBalancer address; resolve provisioning before deploying the agent" >&2
else
  az network nsg rule create -g "$BYOAKS_SUBNET_NSG_RG" --nsg-name "$BYOAKS_SUBNET_NSG" \
    -n Allow-AzureCloud-FoundryRouter-443 --priority 500 --direction Inbound --access Allow --protocol Tcp \
    --source-address-prefixes AzureCloud --destination-address-prefixes "$ROUTER_IP" --destination-port-ranges 443 \
    --query provisioningState -o tsv
fi
```

**D4. 部署并调用应用。** 仍在示例目录运行。成功条件：部署结束、invoke 返回回答、show 显示端点。失败时检查示例和控制器日志以及获准的存储、身份、网络配置；不要自动 purge 资源。

```bash
azd deploy
azd ai agent invoke "Hi"
azd ai agent show
cd "$HOSTING_REPO"
```

**7. E — 在 Azure VM 上部署 E2B Embed 并构建 E2B 的 Code Interpreter 模板。** 使用暴露 `/dev/kvm` 的 Ubuntu 24.04 LTS Gen2 VM（如 `Standard_D4ds_v7`），系统盘 128 GB，装好 Docker Engine 27+ 和 Compose 2.24+，并把当前用户加入 `docker` 组（[E2B 主机要求](https://github.com/e2b-dev/runtime/blob/588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/compose/README.md#requirements)）。模板构建需要这么大的盘：在 50 GB 系统盘上，构建因为给 E2B 数据库留的空间不够而不得不停下（`e-2026-10-15-latest`）。在子网 NSG 中把 E2B 端口限制为你的客户端 CIDR。Compose 栈在 `embed/compose/` 目录下，不在仓库根目录。在 VM 上（通过 SSH）从实测所用的提交 `588e5b9` 下载这两个文件，用我们实测记录的 SHA-256 核对，把大页池设为 4096 页（8 GiB；下载的 `.env` 里没有 `HUGEPAGES` 这一行，Compose 会用 2048，只放得下一个 `code-interpreter-v1` 沙箱），再启动：

```bash
mkdir -p "$HOME/e2b" && cd "$HOME/e2b"
curl -fsSL --remote-name-all "https://raw.githubusercontent.com/e2b-dev/runtime/588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/compose/{compose.yaml,.env}"
printf '%s  %s\n' \
  658429e02665fa9e1cc23411e0897b1e2db1867e6fa9c47fb551ac5a313b6b74 compose.yaml \
  484510816c685a4d6d24bff34d00b05c46306146c0be397507dc215390a182fa .env \
  | sha256sum -c - && printf '\nHUGEPAGES=4096\n' >> .env && docker compose up -d --wait
```

成功标志：`sha256sum` 输出 `compose.yaml: OK` 和 `.env: OK`，随后 `docker compose up` 退出码为 0；它要等 `base` 模板构建完成才会返回（耗时见[实现效果](#实现效果)中「本次路径部署耗时」一行；失败排查见 [If `up` fails](https://github.com/e2b-dev/runtime/blob/588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/compose/README.md#if-up-fails)）。哈希不一致时不会启动任何服务，把整段命令再运行一次即可，它会重新下载这两个文件。

然后把测试团队的构建工作空间调到 8192 MiB，等 5 分钟，再用 E2B 未改动的构建脚本从实测所用的提交 `162a2a2` 构建 `code-interpreter-v1`。这个工作空间是 Embed 内部 `project_limits` 表里的一行，E2B 没有文档说明：用默认的 512 MiB 时构建在第 8 步空间不足（`e-2026-10-15-latest`）；加这一行之后 16 s 开始的构建同样失败，5 分钟后开始的构建通过了这一步（`e-2026-10-17-ci-agent`）：

```bash
cd "$HOME/e2b"
docker compose exec -T postgres psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c "insert into public.project_limits (team_id, max_length_hours, concurrent_sandboxes, concurrent_template_builds, max_vcpu, max_ram_mb, disk_mb, events_ttl_days, default_free_disk_size_mb, max_disk_size_mb, max_free_disk_size_mb, api_team_rps_list) select id, max_length_hours, concurrent_sandboxes, concurrent_template_builds, max_vcpu, max_ram_mb, 8192, events_ttl_days, default_free_disk_size_mb, max_disk_size_mb, max_free_disk_size_mb, api_team_rps_list from public.team_limits where id = (select id from public.teams where name = 'local-dev team')"
sleep 300
sudo apt-get update && sudo apt-get install -y python3-venv
git clone --filter=blob:none https://github.com/e2b-dev/code-interpreter.git
git -C code-interpreter fetch origin 162a2a25b6a5ea5806749a437b96cbdc5bfc087e
git -C code-interpreter checkout 162a2a25b6a5ea5806749a437b96cbdc5bfc087e
python3 -m venv venv-build
venv-build/bin/pip install -r code-interpreter/template/requirements-dev.txt
docker compose exec -T ready cat /run/e2b/sdk.env > sdk.env && chmod 600 sdk.env
(set -a && . ./sdk.env && set +a && cd code-interpreter/template && ../../venv-build/bin/python build_prod.py)
```

成功标志：`psql` 输出 `INSERT 0 1`，构建走完 30 步，最后一行是 `Build finished, took …`（`e-2026-10-15-latest` 在 host a 上为 7m3s）。如果某一步报 `error setting fc metrics`，再运行最后一行即可：在 `e-2026-10-17-ci-agent` 中下一次尝试通过了（两次之间 VM 重启过）。`sdk.env` 里有这套栈的 API key，只留在 VM 上。

回到第 1 步保持打开的 shell，在 `.env` 中把 `E2B_API_URL` 和 `E2B_SANDBOX_URL` 设为这台 VM 的地址并重新加载。安装实测所用的 E2B SDK：`e2b==2.56.0` 和 `e2b-code-interpreter==2.11.0`（需要 Python 3.11+），检查健康端点，在不回显的情况下输入这套栈的 API key（VM 上 `$HOME/e2b/sdk.env` 里的 `E2B_API_KEY`），然后向 Prompt Agent 问一个问题：

```bash
cd "$HOSTING_REPO"
set -a && . "$HOSTING_REPO/.env" && set +a
python -m pip install e2b==2.56.0 e2b-code-interpreter==2.11.0
curl --fail-with-body --show-error --max-time 30 "$E2B_API_URL/health"
read -rsp "E2B_API_KEY: " E2B_API_KEY && export E2B_API_KEY && echo
python tools/e2b_agent.py "Where is Bangkok? Answer in one short sentence."
```

成功标志：`/health` 返回 HTTP 200，响应体为 `Health check successful`；`tools/e2b_agent.py` 打印回答，例如 `Bangkok is the capital city of Thailand in Southeast Asia.`，再在 stderr 打印一行工具调用次数和 `run_code` 耗时，删除它创建的沙箱、会话和 agent 版本后以 0 退出。它使用 `.env` 里的 `PROJECT_ENDPOINT` 和 `ACA_MODEL`，用你的 `az` 登录获取 Foundry 令牌；退出码 2 表示缺少某项设置，1 表示失败或有资源没能删除。

**完成。** 所选方案应已有能回答的应用及可用入口，而不是仅完成了一条测量命令。冷暖启动压测、隔离检查、历史数字重算见 [VALIDATION_CN.md](VALIDATION_CN.md#测试与离线校验)。

**下线仅在资源所有者明确批准后执行，不属于部署必做项。** 下面每条命令单独一个代码块，只运行你明确要释放的资源对应的那条；停止 AKS 只节省计算费，不会让保留资源费用归零。

删除 A 的沙箱：

```bash
python tools/aca_sandbox.py delete
```

停止 C 的集群：

```bash
az aks stop -g "$RESOURCE_GROUP" -n "$AKS_NAME"
```

停止 D 的集群：

```bash
az aks stop -g "$BYOAKS_RESOURCE_GROUP" -n "$BYOAKS_CLUSTER"
```

释放 E 的 VM：

```bash
az vm deallocate -g "$E2B_RESOURCE_GROUP" -n "$E2B_VM_NAME"
```

删除资源组。这会移除共享底座和 A/B/C，`az` 会先要求你确认：

```bash
az group delete -n "$RESOURCE_GROUP" --no-wait
```

**仓库目录。** [`tools/`](tools/) 部署、测量和检查工具 · [`evidence/claims.json`](evidence/claims.json) A–E canonical 声明 · [`evidence/`](evidence/) 脱敏后的实测记录和 `measurements.json` · [`images/`](images/) 图和图标台账 · [`config/`](config/) 配置模板 · [`tests/`](tests/) 离线测试（`python -m pytest -q`，CI 每次推送都会运行）。
