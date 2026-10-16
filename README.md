# Five Ways to Host an Agent Sandbox on Azure: ACA Sandboxes, Foundry Hosted Agent, AKS + agent-sandbox, BYO-AKS, E2B on Azure VM

[![Paths](https://img.shields.io/badge/paths-A%20%C2%B7%20B%20%C2%B7%20C%20%C2%B7%20D%20%C2%B7%20E-0078D4)](#purpose)
[![Measured](https://img.shields.io/badge/measured-East%20US%202%2C%202026--09--22%20to%2010--15-0078D4)](#results)
[![Docs CI](https://github.com/xinyuwei-david/Azure-Agent-Sandbox-Hosting/actions/workflows/docs-ci.yml/badge.svg)](https://github.com/xinyuwei-david/Azure-Agent-Sandbox-Hosting/actions/workflows/docs-ci.yml)

Author: Xinyu Wei · [中文](README_CN.md)

## Purpose

There are two ways to isolate an AI agent in micro-VMs (lightweight VMs with their own kernel) on Azure: run the whole stateful agent inside the session's own micro-VM (paths A–D), or run the agent in Foundry and put only the code its tools execute into a micro-VM sandbox (path E). Either way, you have to pick who runs that micro-VM and its lifecycle: a managed service, Foundry, or you on your own AKS nodes or Azure VM. The five paths make different trade-offs, and their seconds are hard to compare from product pages alone—especially when sandbox boot, private storage volume mounts, and model turns are lumped into one number. This repository applies one comparable stateful interaction contract to all five paths, breaks each stage down separately, gives the steps to reproduce each path, and shows what we measured. A and C share the workshop reflection agent; B uses its distinct Agent Framework agent with ResponsesHostServer; D uses the product group's private-preview sample; E uses a Foundry Prompt Agent calling an E2B Firecracker sandbox tool on an Azure VM, so this is not an identical-container benchmark:

| Question | A · ACA Sandboxes | B · Foundry hosted agent | C · AKS + agent-sandbox | D · BYO-AKS | E · E2B on Azure VM |
|---|---|---|---|---|---|
| Status | GA (2026-09-23) | GA (2026-06) | Pod Sandboxing GA (2025-11-18); agent-sandbox v0.5.2 is open source | **Private preview** | E2B Embed open source (`588e5b9`) on Azure Gen2 VM |
| Who runs the session lifecycle | The ACA service | Foundry | You: controller, gateway, idle sweeper | Foundry, on your cluster | You: E2B orchestrator on your VM, called as a Foundry agent tool |
| Where the session's micro-VM runs | Service-managed compute | Microsoft-managed compute | Your Kata node pool | Your Kata node pool | Your Azure VM with nested virtualization (`/dev/kvm`) |
| Suspend with memory snapshot | Yes | No: idle releases compute, `$HOME` and `/files` are restored | No memory snapshot: you patch `operatingMode`; the pod goes, file state comes back from Blob | Not exercised; confirm preview suspend support with the product group | Yes: `beta_pause` saves Firecracker memory and disk (`vm_state` + `mem_file`) |
| Selectable size / node SKU (docs) | XS: 0.25 vCPU / 0.5 GB<br>S: 0.5 vCPU / 1 GB<br>M (default): 1 vCPU / 2 GB<br>L: 2 vCPU / 4 GB<br>XL: 4 vCPU / 8 GB | 0.5 vCPU / 1 GiB<br>1 vCPU / 2 GiB<br>2 vCPU / 4 GiB<br>No VM SKU to choose | Kata-compatible Gen2 VM SKUs, such as the Dsv3 series; Azure Linux and nested virtualization required | Kata node SKUs within the approved preview requirements; confirm the selectable list with the product group | Gen2 VM SKUs with nested virtualization, such as `Standard_D4ds_v7`; E2B `base` template defaults to 2 vCPU / 512 MB |
| Choose it when | You want per-user micro-VMs, snapshots and no cluster | You want Foundry to run everything and its limits do not bite | You must own the node, the network and the control plane | You need Foundry's agent platform **and** sessions on nodes you own | You want sub-100 ms Firecracker creation and memory snapshots on a VM you own, called as a Foundry agent tool |

Product capabilities come from Microsoft Learn and status from the official announcements linked below; measured claims come from our runs; the last row is our selection guidance. Start with B for a general managed enterprise agent when its limits fit. For a long-running, per-user workload that needs memory snapshots without a cluster, start with A. Use C, D or E when owning the execution nodes is non-negotiable; choose D when Foundry must run the session pods on your AKS cluster, or E when a Foundry Prompt Agent calls self-hosted Firecracker sandboxes on a single Azure VM. E2B Embed is [one machine by design](https://github.com/e2b-dev/runtime/blob/588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/README.md#when-one-node-is-not-enough): more VMs are more independent installs that your client spreads sessions over (`e-2026-10-15-multi`), and E2B's multi-node offer in your own cloud account is Bring Your Own Cloud, operated by E2B, which we did not test.

The selectable row separates four categories: [A's sandbox resource tiers](https://learn.microsoft.com/azure/container-apps/sandboxes-overview#resource-tiers), [B's sandbox sizes](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents#sandbox-sizes), [C/D's node VM SKUs](https://learn.microsoft.com/azure/aks/use-pod-sandboxing), and [E's host Azure Gen2 VM SKU plus E2B template quota](https://github.com/e2b-dev/runtime/tree/588e5b9500b0987bc5a700d91483b03f0ae7d2a2). A node or host VM SKU is not a per-session allocation; Kata pod requests, limits and overhead also constrain each session in C/D, and the E2B template (`base` defaults to `2` vCPU / `512` MB) constrains each Firecracker sandbox in E. Path E serves as a self-hosted open-source Firecracker reference baseline on an Azure VM to cross-check sandbox startup, memory-snapshot resume and concurrency against the Azure-native options (A–D). Node availability and quota vary by region and subscription, and D has additional preview requirements.

Status sources: [A GA announcement](https://techcommunity.microsoft.com/blog/appsonazureblog/azure-container-apps-sandboxes-now-generally-available/4559125), [B GA announcement](https://azure.microsoft.com/updates?id=563596), [C Pod Sandboxing GA](https://azure.microsoft.com/updates?id=526237), and [E open-source E2B Embed runtime (`588e5b9`)](https://github.com/e2b-dev/runtime/tree/588e5b9500b0987bc5a700d91483b03f0ae7d2a2); agent-sandbox and E2B Embed themselves are open-source projects, not Azure services. For C/D, [Kata provides compute isolation only](https://learn.microsoft.com/azure/aks/concepts-pod-sandboxing), not isolation of the control plane, storage/data paths or cluster-admin actions. For E, Firecracker (`v1.14-0.2.0`) on `/dev/kvm` isolates each sandbox micro-VM, while you own the host VM OS, Docker daemon, E2B API authentication and subnet NSG rules.

<img src="images/architecture-en.png" width="900" alt="Five columns A to E. Each shows the client entry, the Microsoft-managed zone and your subscription. A: ACA Sandboxes service and a sandbox micro-VM, with sandbox group, registry and Blob volume in your subscription. B: Foundry Agent Service and a per-session sandbox, with project and Application Insights in your subscription. C: AKS control plane, then controller, Kata pod VM, Kata node pool and Blob PVC in your subscription. D: Foundry Agent Service, then subnet NSG, foundry-system, Kata pod VM per session and registry and storage in your subscription. E: Foundry Agent Service, then Azure VM with E2B Embed Compose stack, Firecracker micro-VM per sandbox and the VM's OS disk holding templates and snapshots in your subscription.">

What the figure shows: who owns each component and where the micro-VM boundary sits. A, C, D and E placement comes from our read-backs; B's VM-isolated boundary comes from Learn. It does not show networking detail, identity flows or the model gateway.

**Execution models and official concurrency quotas (agent container in sandbox vs tool sandbox).** Paths A–D run the entire stateful agent container inside the session's micro-VM, whereas path E runs the agent in Foundry's control plane and calls an isolated micro-VM sandbox only when executing code or tools:

| Execution pattern | Where the agent process runs | What runs in the micro-VM | Documented concurrency & quota limits | Micro-VM active for whole session? | Idle pause & scale-to-zero |
|---|---|---|---|---|---|
| **A / B / C / D (stateful agent container in sandbox)** | Inside the micro-VM sandbox (`1:1` bound to the session) | The whole agent container (ACA Cloud Hypervisor / Foundry sandbox / AKS Kata) | **A**: [500 concurrent active cores](https://sandboxes.azure.com/docs/sandboxes/limits) default ([2,000 cores standard limit](https://learn.microsoft.com/azure/container-apps/quotas#sandboxes-and-express-quotas), `20,000` cores verified in our subscription; `3,000` requests/min; stopped sandboxes do not count)<br>**B**: [1:1 per active session](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents#scaling-and-right-sizing) (`20` GiB disk, `50` MB per uploaded file)<br>**C / D**: bounded by your AKS Kata node-pool vCPU/RAM quota | **Yes** — the micro-VM stays Running for the active session | **A**: memory snapshot suspend (`1.58–2.83` s resume)<br>**B**: idle timeout or `:stop` releases compute and keeps `$HOME`<br>**C**: patch `operatingMode` deletes pod and restores from Blob |
| **E (Foundry Agent Service + E2B on Azure VM tool sandbox)** | Foundry managed control plane (serverless, billed by model tokens) | Only the code the agent's tools run: a Firecracker micro-VM on your Azure Gen2 VM (`/dev/kvm`) | One Embed install is one VM, bounded by its hugepage pool: the default `HUGEPAGES=2048` held `7` idle `base` sandboxes on a `Standard_D4ds_v7`, and `8` sessions at once answered `8/8` on 2026-10-14 and `7/8` on 2026-10-15; a second, independent VM added its own `7` (`14/16`); there is no shared scheduler between installs | **On demand** — only during `run_in_e2b_sandbox` tool calls; can `beta_pause` between turns | Per-sandbox memory snapshot (`0.09` s resume), while the host Azure VM (`0.344` USD/h) stays running |

**Consumer-facing (ToC) and high-concurrency selection trade-offs: cold start, warm pools, and cost (ACA vs AKS Spot vs E2B):**
- **Cold-start speed and warm pools:** For interactive ToC workloads, cold-start latency and unit cost are the two primary criteria. Without a prewarmed pool, Kubernetes-based sandboxes (C/D) incur image-pull or volume-mount latency on new nodes unless you maintain your own warm pool (such as `SandboxWarmPool` in `agent-sandbox`). ACA Sandboxes (A, <!--v:a.attr.image.median-->2.31<!--/v--> s median without a private Blob volume) start from a platform-managed warm pool, while E2B on a running Azure VM (E) boots a Firecracker micro-VM from a local template snapshot in <!--v:e.create.median-->0.07<!--/v--> s (<!--v:e.bench20.create.range-->0.051–0.089<!--/v--> s on host).
- **Cost structure — lifecycle + state + resume speed (ACA strength) vs Spot nodes (AKS/VM strength):** Across bursty user sessions with long idle tails, **ACA (A) is stronger on lifecycle management, state preservation and resume speed**: stopped sandboxes preserve full memory and disk state (<!--v:a.attr.resume_small.range-->1.58–2.79<!--/v--> s no-volume / <!--v:a.resume.median-->2.83<!--/v--> s Blob-volume resume) while billing zero CPU/memory and consuming zero active-core quota. Conversely, **AKS (C) and self-hosted VMs (E) can use [Azure Spot node pools / Spot VMs](https://learn.microsoft.com/azure/aks/spot-node-pool)** (or Reserved Instances / Savings Plans) to lower raw vCPU-hour compute cost for sustained high-utilization or eviction-tolerant workloads—an option serverless ACA does not expose. When using AKS Spot for stateful sandboxes, your application must handle Spot eviction and state recovery from external storage.

## Results

Words used in the results:

| Term | Meaning |
|---|---|
| Cold | A new session or sandbox until its first answer arrives |
| Warm | A follow-up turn in the same running session |
| Resume | An already suspended session: resume request → first answer; stop and idle waiting are excluded |
| Pod lost | Delete the session's pod or sandbox; Kubernetes or the caller creates a replacement |
| Micro-VM | A lightweight VM with its own guest kernel per sandbox, session or pod (Kata Containers on AKS; Cloud Hypervisor read back inside ACA; Firecracker on KVM in E2B) |

**Where each path's micro-VM runs.** Measured read-backs for A, C, D and E, plus Learn's documented boundary for B:

| | A · ACA Sandboxes | B · Foundry hosted agent | C · AKS + agent-sandbox | D · BYO-AKS | E · E2B on Azure VM |
|---|---|---|---|---|---|
| Boundary | One micro-VM per sandbox | Per-session VM-isolated sandbox (Learn) | One Kata pod VM per Sandbox | One Kata pod VM per session | One Firecracker micro-VM per sandbox |
| VMM and hypervisor | `vmm_type` <!--v:a.vmm.value-->cloudhypervisor<!--/v--> from the API; the docs name no hypervisor | Not published; only VM isolation is documented | Cloud Hypervisor on Microsoft Hyper-V (Learn) | Same as C | <!--v:e.vmm.value-->firecracker<!--/v--> (<!--v:e.isolation.firecracker_version-->v1.14-0.2.0<!--/v-->) on Linux KVM (`/dev/kvm`), from the host's process list |
| Kernel read | Guest <!--v:a.isolation.guest_kernel-->6.12.8+<!--/v--> | Not exposed; not read back | Pod <!--v:c.isolation.guest_kernel-->6.6.137.mshv1-1.azl3<!--/v-->, runc pod <!--v:c.isolation.system_node_kernel-->6.8.0-1067-azure<!--/v--> | Kata pool nodes <!--v:d.node_kernel.value-->6.6.137.mshv2-2.azl3<!--/v-->; not read inside a session pod | Guest <!--v:e.isolation.guest_kernel-->6.1.177+<!--/v-->, host VM <!--v:e.isolation.host_kernel-->6.17.0-1022-azure<!--/v--> |
| Who owns the node | Microsoft | Microsoft | You | You | You |

B's per-session VM-isolated boundary is a `SOURCE_FACT`, not a local VMM or kernel read-back. C and D use the same Kata runtime class, so isolation does not separate them: who runs the platform does. E runs Firecracker directly on `/dev/kvm` inside your Azure Gen2 VM.

**The seconds, broken down by stage.** Earlier summaries combined bare sandbox startup, private Azure Blob volume mounts, and the first agent turn into one cold-start number—making A look slow because its full workshop config attached a private Blob volume (+<!--v:a.blob_mount_overhead.value-->21.94<!--/v--> s), even though A natively supports `Memory` snapshots and does not need an external Blob volume to keep session state across suspend. Below, each stage is separated. A is the median of three runs on 2026-10-09 plus its attribution matrix; B is a single run on 2026-09-27 plus three session-API runs on 2026-10-15; C is a single run on 2026-09-27; D is one benchmark campaign on 2026-09-29; E is one benchmark campaign on 2026-10-14 (the second-host and two-host runs of 2026-10-15 are in the run table below). A and C use the workshop reflection agent; B uses its Agent Framework agent with ResponsesHostServer; D uses the private-preview sample; E uses a Foundry Prompt Agent calling an E2B sandbox tool. All use the same model and a stateful interaction, but not the same container. B's 2026-09-27 run and D were called through the Foundry endpoint from a laptop in China (Azure round trip <!--v:d.client_rtt.range-->320–800<!--/v--> ms); B's 2026-10-15 session runs came from a Windows VM in Japan East through an Azure API Management gateway; E's benchmark driver ran on the E2B host VM in East US 2; A's answers were timed inside the sandbox and C's at its LoadBalancer. Compare within a row as a field report, not as a controlled product benchmark:

**How startup is timed, verbatim test prompts, and executable benchmark scripts.** Pure sandbox or pod startup is timed from issuing the CLI/SDK creation request until the sandbox or pod status reaches ready (`Running` / `Active` / `Ready`), before sending any LLM prompt:

| Protocol & paths | Sandbox / pod ready clock (start → end) | Verbatim prompts sent in order | Executable script in repository |
|---|---|---|---|
| **Stateful agent & suspend/resume (`A`, `B`, `C`, `E`)** | **A**: SDK `_do_create_sandbox` → `get_sandbox` state `Running`<br>**B**: `POST .../endpoint/sessions` → `active`<br>**C**: `kubectl apply` / `operatingMode: Running` → Sandbox `Ready`<br>**E**: `Sandbox.create("base")` → Firecracker `Running` | A, B and E, in order — Turn `1`: `"Where is Bangkok? Answer in one short sentence."`<br>Turn `2` (warm): `"How many questions have I asked before this one? Number only."`<br>Turns `3–4` (after suspend/resume): `"How many questions have I asked before this one? Number only."`<br>C: request text not kept | [`tools/measure_aca.py`](tools/measure_aca.py)<br>[`tools/measure_sessions.py`](tools/measure_sessions.py)<br>[`tools/measure_e2b.py`](tools/measure_e2b.py) (`agent` mode) |
| **Responses cold, warm, concurrency & recovery (`D`, `E`)** | **D**: Pod `creationTimestamp` → `Ready` condition<br>**E**: `Sandbox.create("base")` → Firecracker `Running` | **D** — Cold (`n` new sessions): `"Reply with exactly COLD-{i}"`<br>Warm (`1` session): `"Remember the code word LANTERN-7. Reply only OK."` → `"What is the code word? Reply with the word only."` → `"Reply with exactly WARM-{i}"`<br>Concurrency (`4` and `8` at once): `"Remember SCALE-{i}. Reply only OK."` → `"What did I ask you to remember? Word only."`<br>**E** — the same steps, each prompt telling the agent to use its sandbox tool, such as `"Use run_in_e2b_sandbox to print COLD-{i}, then reply with exactly COLD-{i}"`; every prompt is in [VALIDATION.md](VALIDATION.md#e-2026-10-14-perf-cold-start-follow-ups-concurrency-and-sandbox-replacement-on-e2b) | [`tools/measure_responses.py`](tools/measure_responses.py)<br>[`tools/measure_e2b.py`](tools/measure_e2b.py) (`perf` mode) |

A's and E's A-protocol cold and resume-to-answer numbers are component sums, not a single end-to-end client stopwatch: SDK create or resume wall time plus the answer timed inside the sandbox (A) or Prompt Agent turn (E). B's session-API cold start likewise adds two client requests: create the session, then the first answer; B's 2026-09-27 run used `azd ai agent invoke` and kept no request text. C's cold number is likewise apply-to-Ready plus first-answer time. Resume starts after suspension has finished; stop and idle waiting are excluded. B's follow-up row lists the 2026-09-27 run (gateway model route) and the 2026-10-15 runs (direct model route). Every clock, its start and end, and where it runs are in [VALIDATION.md](VALIDATION.md#architecture-and-metrics).

**Do not rank the five products by these seconds.** Clock locations, prompts, reasoning settings, output token counts, image cache and sample sizes were not uniformly controlled or fully recorded across paths. The same model name does not make these a matched latency benchmark. Numerical sanity checks can reject invalid timings; they cannot establish product performance or fill missing instrumentation.

<!-- BEGIN GENERATED: comparison -->
| Observed or docu&shy;mented | A · ACA Sand&shy;boxes | B · Foundry hosted agent | C · AKS + agent-sandbox | D · BYO-AKS | E · E2B on Azure VM |
|---|---|---|---|---|---|
| **Cold start = sum of** | sandbox create → Running + first answer (timed inside the sandbox) | create session → `active` + first answer (two client requests) | <code>kubectl </code><br><code>apply</code>&#8203; → Sandbox Ready (includes the Blob PVC mount) + first answer (at the Load&shy;Balancer) | session pod created → Ready + pod Ready → first answer (endpoint, session and agent path) | E2B sandbox create → Running + first answer (Prompt Agent turn that calls the sandbox tool) |
| **Pure cold start, no external volume (total)** | **6.19 s** derived (2.31 s + 3.88 s, medians of separate runs) | **12.31 s** median (11.65–&#8203;12.36; n=3), added per run; one request that auto-creates the session on the first <code>/</code><br><code>responses</code>&#8203;: 9.43 s (gateway model route) / 5.29 s (direct), n=1 each | not measured: C keeps state across suspend only through the Blob PVC, so every measured cold start mounted it | **25.49 s** median (23.53–&#8203;26.7; n=5), one request via the Foundry endpoint | **4.26 s** median (2.89–&#8203;8.44; n=3), added per run (A protocol); 3.6 s median (2.54–&#8203;7.94; n=5) in one request (D protocol) |
| └ part 1: sandbox, session or pod ready | 2.31 s median (1.6–&#8203;2.7; n=3) (image only); with VNet 1.97–&#8203;2.52 s (n=2), port 2.3–&#8203;2.33 s (n=2) | 6.69 s median (6.51–&#8203;6.87; n=3), <code>POST </code><br><code>.../</code><br><code>endpoint/</code><br><code>sessions</code>&#8203; → `active` | not measured without the PVC | 8–&#8203;10 s (n=6) with the image cached; 25 s on a fresh node (n=2) | 0.07 s median (0.06–&#8203;0.14; n=3) in the agent runs; 0.051–&#8203;0.089 s (n=20) in the on-host micro&shy;bench&shy;mark |
| └ part 2: ready → first answer | 3.88 s median (2.82–&#8203;5.55; n=3), timed inside the sandbox | 5.62 s median (4.79–&#8203;5.85; n=3) on the active session; the service recorded 2–&#8203;4 s of it as gener&shy;ation | 12.75 s (n=1), at the Load&shy;Balancer | 15.49 s median (14.01–&#8203;16.16; n=3) after pod Ready (agent turn 2–&#8203;5 s) | 4.12 s median (2.82–&#8203;8.38; n=3) (A protocol); 3.44 s median (2.28–&#8203;7.75; n=5) (D protocol) |
| **Cold start with a private Blob volume (total)** | **28.0 s** median (27.07–&#8203;50.41; n=3); SDK create + answer inside sandbox | no external volume (the platform restores `$HOME` and `/files`) | **57.65 s** (n=1; apply → Ready 44.9 s + answer 12.75 s) | no external volume in the session pod | no external volume (tem&shy;plates and snap&shy;shots stay on the host VM's OS disk) |
| └ volume overhead | +21.94 s median vs image only (create → Running 24.25 s median (24.12–&#8203;44.86; n=3)); Memory snap&shy;shots need no volume | none | not sep&shy;arable: no run without the PVC (apply → Ready 44.9 s includes it, n=1) | none | none |
| **Follow-up turn, same session** | 1.05 s median (1.04–&#8203;1.54; n=3) | 4.03, 5.54 s (n=2) (<code>b-</code><br><code>2026-</code><br><code>09-</code><br><code>27</code>&#8203;, gateway model route); 4.59 s median (4.42–&#8203;4.81; n=3) (<code>b-</code><br><code>2026-</code><br><code>10-</code><br><code>15-</code><br><code>sessions</code>&#8203;, direct model route) | 1.96 s (n=1) | 12.9 s median (11.17–&#8203;16.42; n=3) | 2.95 s median (2.83–&#8203;3.92; n=3) (A protocol); 3.39 s median (3.19–&#8203;5.03; n=3) (D protocol); on-host sandbox command 0.007–&#8203;0.01 s (n=20) |
| **Suspend / pause and wake until ready** | stop 7.56 s median (5.97–&#8203;9.31; n=3); resume → Running 1.58–&#8203;2.79 s (n=7, no volume), 2.83 s median (1.61–&#8203;3.02; n=3) (with Blob volume) | `:stop` → idle 3.05 s median (2.9–&#8203;7.71; n=3); compute released, `$HOME` kept, no memory snapshot; wakes on the next request (next row) | suspend → pod gone 9.7 s (n=1); resume → Ready 17.1 s, Load&shy;Balancer healthy 26.1 s (n=1) | Not exer&shy;cised; confirm preview suspend support with the product group | pause 0.13 s median (0.11–&#8203;0.15; n=3) (on host 0.051–&#8203;1.81 s (n=20)); resume → Running 0.09 s median (0.08–&#8203;0.11; n=3) (on host 0.086–&#8203;0.62 s (n=20)) |
| **Resume request → first answer (stop excluded)** | 14.45 s median (12.44–&#8203;17.22; n=3); sep&shy;arately reported resume-only median 2.83 s | 12.02 s median (11.66–&#8203;12.35; n=3): the next turn on the stopped session gets new compute with `$HOME` restored; file written before the stop read back 3/3, question count kept growing 3/3 | 34.2 s (n=1; Ready 17.1 s, Load&shy;Balancer healthy 26.1 s) | Not exer&shy;cised; confirm preview suspend support with the product group | 6.48 s median (4.73–&#8203;12.82; n=3); sep&shy;arately reported resume-only median 0.09 s |
| **Pod or sandbox lost → ready again** | not exer&shy;cisable: no API injects host loss, and deleting a sandbox ends it | not exer&shy;cisable: no API kills only a session's sandbox; explicit stop and resume are above | 23.4 s (n=1); same Sandbox state restored | 23.9 s (n=1); deleted session con&shy;tinuity not tested | 0.1 s (n=1); another live session answered in 2.61 s |
| **Idle policy (official docs)** | [Docs](https://learn.microsoft.com/azure/container-apps/sandboxes-overview#lifecycle-states): config&shy;urable idle auto-suspend; Memory or Disk snapshot mode | [Docs](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents#sessions): 2–&#8203;60 min idle timeout (default 15); compute released, $HOME and /files per&shy;sisted; session deleted after 30 days of in&shy;activity | [Official API](https://github.com/kubernetes-sigs/agent-sandbox/blob/v0.5.2/docs/api.md): shutdown&shy;Time is sched&shy;uled expiry, not request-idle de&shy;tection; imple&shy;ment request-idle re&shy;cycling yourself | No verified public official idle policy; confirm with the product group | [E2B docs](https://e2b.dev/docs/sandbox): per-sandbox timeout (default 5 min) and explicit <code>beta_</code><br><code>pause</code>&#8203; / `connect` |
| **Capacity** | server&shy;less; default 500 con&shy;current active cores (2000 standard limit, 20000 in our sub&shy;scrip&shy;tion) and 3000 requests/&#8203;min ([docs](https://sandboxes.azure.com/docs/sandboxes/limits)); stopped sand&shy;boxes do not count | one VM-isolated sandbox per session, scaled per session with no replica count or warm pool to con&shy;figure ([docs](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents#scaling-and-right-sizing)); up to 20 GiB disk per session (20% system-reserved) and 50 MB per uploaded file | your Kata node pool | observed at most 5 per Standard_&#8203;D4s_&#8203;v5 node; 12 on 3 nodes; <code>500 </code><br><code>session_</code><br><code>creation_</code><br><code>failed</code>&#8203;, <code>429 </code><br><code>aks_</code><br><code>quota_</code><br><code>exceeded</code>&#8203; | one machine per install, by design ([E2B](https://github.com/e2b-dev/runtime/blob/588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/README.md#when-one-node-is-not-enough)); 2026-10-14 on 1 Standard_&#8203;D4ds_&#8203;v7 VM: 4 at once 4/4, 8 at once 8/8; 2026-10-15 on one host 7/8 and on two inde&shy;pendent hosts 14/16; the default hugepage pool held 7 `base` sand&shy;boxes per host |
| **Path setup in our run** | 146.6 s (sandbox group, VNet con&shy;nection, disk image, volume, sandbox) | 161 s (<code>azd </code><br><code>deploy</code>&#8203;; model route: gateway (APIM)) | 812.9 s (prepare script, private link, apply) | 854 s (roles, <code>azd </code><br><code>provision</code>&#8203;, <code>azd </code><br><code>deploy</code>&#8203;; author's console, not kept) | 177 s (Docker Engine 33.0 s + E2B Compose and base template 144 s) |

**Local configuration and observation, not official idle policy:** A used Memory mode with a 900 s auto-suspend setting. D's oldest pod was still Running at least 87 min after creation; this is pod age, not idle duration or a reclamation timeout.
<!-- END GENERATED: comparison -->

What stands out:
- **Separating bare sandbox creation from external Blob volume mounting changes the picture for A:** without the private Blob volume, A created a custom-image sandbox in <!--v:a.attr.image.median-->2.31<!--/v--> s median (<!--v:a.attr.small.range-->1.6–2.7<!--/v--> s across image, VNet or port alone), giving a derived cold first answer of <!--v:a.cold_no_volume.value-->6.19<!--/v--> s (`<!--v:a.attr.image.median-->2.31<!--/v-->` s + `<!--v:a.first_answer.median-->3.88<!--/v-->` s), and A's warm follow-up of <!--v:a.warm.median-->1.05<!--/v--> s was the fastest among all five paths. Attaching the private Blob volume added +<!--v:a.blob_mount_overhead.value-->21.94<!--/v--> s median (raising create to <!--v:a.attr.vnetvolume.range-->15.79–25.12<!--/v--> s in attribution and <!--v:a.create.median-->24.25<!--/v--> s in the full agent runs). Because A has native `Memory` snapshots (unlike C, which deletes the pod on suspend), A does not need an external Blob volume merely to preserve session state across suspend.
- **E (E2B on Azure VM) delivers sub-100 ms Firecracker creation and snapshot wake on a single VM:** sandbox creation took <!--v:e.create.median-->0.07<!--/v--> s median in the agent runs (<!--v:e.bench20.create.range-->0.051–0.089<!--/v--> s across 20 runs of the on-host microbenchmark), resume took <!--v:e.resume.median-->0.09<!--/v--> s (<!--v:e.bench20.resume.range-->0.086–0.62<!--/v--> s on host), and all 4/4 and 8/8 concurrent sessions succeeded on one `Standard_D4ds_v7` VM on 2026-10-14. On 2026-10-15 the same 8 sessions answered <!--v:e.multi.one_host.answered-->7<!--/v-->/8 on one VM, because each 512 MB `base` sandbox reserves <!--v:e.multi.hugepages.per_sandbox-->256<!--/v--> hugepages when it is created and the default pool fits <!--v:e.multi.hugepages.fit-->7<!--/v-->; a second, independent VM added its own 7. Embed is one machine by design: you own the VM OS, Docker Compose stack, network rules, hugepage sizing and any spreading over several VMs, and a paused sandbox can only resume on the VM that paused it.
- **D (BYO-AKS) is in Private Preview to validate the product shape, with latency optimization targeted for Public Preview:** in this preview build, the session pod was Ready in <!--v:d.pod_ready.range-->8–10<!--/v--> s inside a <!--v:d.cold.range-->23.53–26.7<!--/v--> s end-to-end range (<!--v:d.first_after_ready.median-->15.49<!--/v--> s median after pod Ready), while the same model called directly from the same laptop took <!--v:d.model_direct.median-->2.69<!--/v--> s (median, low reasoning effort; not a matched agent-configuration benchmark). The uninstrumented remainder is the endpoint, session and agent path collectively; it is not a measured gateway component. Per the product group, Private Preview focuses on validating the hybrid architecture (Foundry control plane + customer-owned AKS Kata node pool), and performance optimization is planned for Public Preview with the target of matching fully managed Foundry Hosted Agents (path B).
- In the observed D preview build, plan capacity conservatively by sessions opened, not only requests active; the pod-age observation does not establish an idle eviction timeout.

**Measured runs.** Grouped A–E, then by date from oldest to newest within each path, in the same order as [VALIDATION.md](VALIDATION.md), which records each run's input, procedure, result and boundary:

<!-- BEGIN GENERATED: runs -->
| Run | Path | Scenario | Result |
|---|---|---|---|
| `a-2026-09-27-setup` | A | first deployment, wake on request | setup 146.6 s; a request to a stopped sandbox answered in 23.7 s; kernel `6.12.8+` |
| `a-2026-10-09-agent` | A | full agent, 3 runs | cold 28.0 s, warm 1.05 s, resume → answer 14.45 s (medians); vmm `cloudhypervisor` in 3/3; history grew 3/3 |
| `a-2026-10-09-attribution` | A | create time by configuration | image, VNet or port alone 1.6–2.7 s; adding the private Blob volume 15.79–25.12 s |
| `a-2026-10-09-late-mount` | A | start first, mount Blob later | start 3.99–7.2 s, then mount 12.4–20.29 s (n=2) |
| `b-2026-09-27` | B | deploy, new session, follow-ups; gateway model route | deploy 161 s; new session 9.43 s; follow-ups 4.03, 5.54 s |
| `b-2026-10-15-sessions` | B | explicit session lifecycle, 3 runs | create → active 6.69 s, first answer 5.62 s, follow-up 4.59 s, stop → idle 3.05 s, resume → answer 12.02 s (medians); file kept 3/3 |
| `c-2026-09-27` | C | Kata Sandbox, pod loss, suspend/resume | pod kernel `6.6.137.mshv1-1.azl3` vs runc pod on the Ubuntu system pool `6.8.0-1067-azure`; pod lost → Ready 23.4 s; resume → answer 34.2 s |
| `d-2026-09-29-placement` | D | where a session runs | every session pod `kata-vm-isolation` on your node pool after NSG rule `Allow-AzureCloud-FoundryRouter-443` |
| `d-2026-09-29-perf` | D | cold, warm, 4 and 8 at once | cold 25.49 s, warm 12.9 s (medians); 4 at once 0/4, 8 at once 2/8 answered (pool full) |
| `d-2026-09-29-recovery` | D | delete a session pod | replacement Ready in 23.9 s; a different live session answered in 14.8 s; deleted session continuity not tested |
| `e-2026-10-14-agent` | E | Prompt Agent + E2B, 3 runs + 20-run microbench | create 0.07 s (on host 0.051–0.089 s), cold 4.26 s, warm 2.95 s, resume → answer 6.48 s (medians); VMM `firecracker` in the host's process list; history grew 3/3 |
| `e-2026-10-14-perf` | E | cold, warm, 4 and 8 at once, replacement | cold 3.6 s, warm 3.39 s (medians); 4 at once 4/4, 8 at once 8/8 answered; replacement Ready in 0.1 s |
| `e-2026-10-15-latest` | E | newest SDK; E2B's official code-interpreter template | e2b 2.56.0: history grew 3/3, create 0.06 s, resume 0.08 s (medians); code-interpreter built only after raising three host defaults; 10/11 checks passed in 4/4 runs, JavaScript failed in all |
| `e-2026-10-15-multi` | E | two independent E2B hosts: second host, at once, idle, host stop | host b: history grew 3/3, create 0.06 s; at once 7/8 on one host, 14/16 on two; with host a's stack stopped, host b kept serving and host a's paused sandbox could not resume on host b |
<!-- END GENERATED: runs -->

**Limits.**
- One region (East US 2). A full-agent latency has n=3. B is one end-to-end run plus three session-API runs, and C is one end-to-end run. D is one benchmark campaign: cached-image cold n=5, warm n=3, and one placement and one recovery observation. E is one benchmark campaign on a single `Standard_D4ds_v7` VM: A-protocol n=3, D-protocol cold n=5 and warm n=3, concurrency 4 and 8, and on-host microbenchmark n=20; plus, on 2026-10-15, the A protocol on a second VM n=3, 8 and 16 sessions at once over one and two VMs, idle capacity n=3, one host stop, the newest SDK n=3 and E2B's code-interpreter checks n=4. Repeat them with the live measurement commands in VALIDATION before you rely on a number.
- These are implementation observations, not product benchmarks or SLAs. The docs state sub-second sandbox start for A from prewarmed pools; our full specification with a private Blob volume did not get there, whereas image-only creation took <!--v:a.attr.image.median-->2.31<!--/v--> s median.
- D is a private preview focused on validating the deployment shape; its behaviour (placement, idle reclaim, limits, and latency before Public Preview optimization) may change, and its onboarding needs the product group's sample and enablement.
- Not measured: B's resume after the idle timeout (resume after an explicit stop is measured), A's and B's pod or host loss (neither service offers a way to inject it), the Foundry-governed agent calling an ACA sandbox per task (the pattern Microsoft describes since GA), E2B Bring Your Own Cloud and private cloud (E2B's multi-node offers), the official Azure Terraform module's scale-set replacement from a fresh disk (blocked in our subscription by a storage-account policy), and the loss of a whole E2B VM or its disk.
- Cost: D's two-node floor is <!--v:d.cost_floor.value-->0.484<!--/v--> USD/h for two `Standard_D4s_v5` nodes and the AKS Standard tier; E's single-VM floor is <!--v:e.cost_floor.value-->0.344<!--/v--> USD/h for one `Standard_D4ds_v7` VM, one Standard static public IP and a 50 GB Premium SSD P6 disk at East US 2 retail prices. Check your own prices.

## Steps

**Deploy first, then use the agent.** These steps follow the [pinned colleague workshop](https://github.com/oxcp/ainotes/tree/905f2c2/agenthost): shared foundation, the selected hosting path, and an actual application call. Benchmarking and evidence replay are optional and live in VALIDATION, not on the deployment path.

**Execution boundary:** the original deployments produced the retained historical results, but this parameterized sequence has not been re-run end to end in a fresh subscription. D also requires the product group's private sample and approval. Offline CI does not certify a successful cloud deployment.

| Order | Where | Action | Entry |
|---|---|---|---|
| 1 | Workstation | Clone, configure and sign in | `config/.env.example` |
| 2 | Azure subscription | Create the shared foundation | workshop `module-01/setup.sh` |
| 3 | C | Build the image, create AKS, deploy the Sandbox and open the app | workshop `module-03` |
| 4 | A | Create the sandbox group and deploy the agent sandbox | workshop `module-04` + `tools/aca_sandbox.py` |
| 5 | B | Deploy the hosted agent and invoke it | workshop `module-02` |
| 6 | D | Bind an existing AKS, deploy and invoke the private-preview agent | product-group sample |
| 7 | E | Deploy E2B Embed on an Azure Gen2 VM and invoke it from a Foundry Prompt Agent | `e2b-dev/runtime` |

**A = ACA Sandboxes, B = Foundry hosted agent, C = AKS + agent-sandbox, D = BYO-AKS, E = E2B on Azure VM**. Upstream calls module-02 Solution A, module-03 Solution B and module-04 Solution C. Use module numbers when reading it. Run only the path you need: B needs steps 1–2; the full A example reuses the image and network created in step 3. ACA itself does not require AKS. D uses an existing cluster and its own approved sample, not an automatically created cluster from this page. E runs the open-source E2B Embed Docker Compose stack on a single nested-virtualization Azure VM.

**Prerequisites.** Bash, Git, curl, Python 3.10+ with the venv module (on Ubuntu/Debian install `python3-venv`), Azure CLI 2.80+, kubectl and azd 1.34+; install the Foundry extension with `azd ext install microsoft.foundry`. You need subscription Owner, or Contributor plus Role Based Access Control Administrator, and model quota in your selected region. For A, your identity also needs the `Container Apps SandboxGroup Data Owner` role ([Learn](https://learn.microsoft.com/azure/container-apps/sandboxes-overview#prerequisites)); the workshop's `sandbox-deploy.sh` assigns it when it can resolve your signed-in user and otherwise only prints a warning. Use a non-production subscription. For C, provide your actual public egress CIDR; this HTTP workshop app is not a production HTTPS/login deployment.

**1. Clone and configure.** Clone into new directories, then edit `.env`: set `SUBSCRIPTION_ID`, `LOCATION` and `RESOURCE_GROUP`; set `C_ALLOW_CIDR` if using C. Leave `SN` until step 2.

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

After editing `.env`, sign in and run the upstream prerequisite checker. Resolve failed tool, permission or quota prerequisites before creating resources. Keep this shell open: it holds `HOSTING_REPO`, the stable return directory, and the activated `.venv`.

```bash
az login
set -a && . "$HOSTING_REPO/.env" && set +a
az account set --subscription "$SUBSCRIPTION_ID"
(cd "$WORKSHOP_DIR/agenthost" && chmod +x check-prerequisites.sh && ./check-prerequisites.sh)
```

**2. Create the shared foundation.** [Module 1](https://github.com/oxcp/ainotes/blob/905f2c2/agenthost/module-01/README.md) creates the Foundry project/model, APIM, ACR, Storage and identity.

```bash
(cd "$WORKSHOP_DIR/agenthost/module-01" && chmod +x setup.sh && ./setup.sh)
az group show -g "$RESOURCE_GROUP" --query tags.deploymentSN -o tsv
```

Success: `Template deployed successfully.` and a non-empty suffix from the second command. Paste that suffix into `SN` in `.env`, then reload it so the derived resource names change together. Do not continue with `YOUR-DEPLOYMENT-SUFFIX`.

```bash
set -a && . "$HOSTING_REPO/.env" && set +a
```

**3. C — Deploy the AKS application.** Follow [Module 3](https://github.com/oxcp/ainotes/blob/905f2c2/agenthost/module-03/README.md). Preparation creates AKS/Kata, controller, image and PVC; it does not deploy the application. The separate `kubectl apply` creates the Sandbox and its Service.

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

Success: the Sandbox reaches `Ready`. Now allow only your configured egress CIDR, obtain the actual application URL, and make a real request:

```bash
if [ -z "$C_ALLOW_CIDR" ] || [[ "$C_ALLOW_CIDR" == YOUR-* ]]; then
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

If the first line prints the `C_ALLOW_CIDR` message, nothing else ran: set it, reload `.env` and run the block again. 
Open the printed URL in a browser to use the chat page. `/ready` must succeed and `/reflect` must return a non-empty `response`; a Ready pod alone is not an answering application. On failure inspect `kubectl get pods`, `kubectl describe pod` and `kubectl logs` in `NAMESPACE`; for unreachable HTTP also check the egress CIDR, Service address and network rules.
 Following the workshop, `aca-subnet` goes into the VNet of the AKS node resource group; [AKS documents modifying resources there as unsupported](https://learn.microsoft.com/azure/aks/faq) and deletes that group with the cluster. Treat this as a workshop shortcut; outside the workshop, give the sandbox group a delegated subnet in a VNet you own.
**4. A — Deploy the ACA sandbox agent.** [Module 4](https://github.com/oxcp/ainotes/blob/905f2c2/agenthost/module-04/README.md) creates the sandbox group. Its disk-image and sandbox steps are separate; the SDK commands below perform those operations rather than replay measurements. This full example reuses step 3's image/network. Choose a free `ACA_SUBNET_PREFIX` inside that VNet.

```bash
(cd "$WORKSHOP_DIR/agenthost/module-04" && chmod +x sandbox-deploy.sh && ./sandbox-deploy.sh)
NODE_RG=$(az aks show -g "$RESOURCE_GROUP" -n "$AKS_NAME" --query nodeResourceGroup -o tsv)
VNET=$(az network vnet list -g "$NODE_RG" --query "[0].name" -o tsv)
az network vnet subnet create -g "$NODE_RG" --vnet-name "$VNET" -n aca-subnet \
  --address-prefixes "$ACA_SUBNET_PREFIX" --delegations Microsoft.App/environments --query id -o tsv
```

Paste the printed subnet ID into `ACA_SUBNET_ID` in `.env`, then run from this repository:

```bash
cd "$HOSTING_REPO"
set -a && . ./.env && set +a
python tools/aca_sandbox.py vnet
python tools/aca_sandbox.py image
python tools/aca_sandbox.py volume
python tools/aca_sandbox.py create
python tools/aca_sandbox.py ask "Where is Bangkok? Answer in one short sentence."
```

Success: `create` reports Running and `ask` returns an actual answer. The answer is requested through sandbox exec; direct browser ingress is not implied. For the browser-port deployment use Module 4's port/IP configuration. If a setting is missing, fill it before retrying; image access failures require ACR permission, and private Blob access requires the VNet and private endpoint.

**5. B — Deploy and call the hosted agent.** Use [Module 2](https://github.com/oxcp/ainotes/blob/905f2c2/agenthost/module-02/README.md) from a new working directory outside the source clone. Bind the existing project, then deploy; do not run `azd provision` for B.

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

Success: deployment finishes and `invoke` returns a real answer. `show` provides the deployed endpoint for API clients; the Foundry agent playground can also invoke it. Keep the default gateway route unless intentionally changing it. If deployment remains creating, inspect `azd ai agent monitor` and the portal status rather than treating timeout as success or automatically deleting the agent.

**6. D — Private-preview deployment.** This path is blocked without the product group's sample and subscription approval. Before running it, fill the BYOAKS values in `.env`, including `BYOAKS_SAMPLE_DIR`, and configure the sample's `AKS_RESOURCE_ID`, `HOSTING_IDENTITY_RESOURCE_ID`, `WORKLOAD_IDENTITY_RESOURCE_ID`, `STORAGE_ACCOUNT_RESOURCE_ID`, `ACR_RESOURCE_ID` and `APPLICATIONINSIGHTS_RESOURCE_ID` using its current guide. Feature registration alone is not approval.

**D1. Prepare the existing cluster's Kata pool.** Confirm this node SKU is available for your subscription/region and meets the approved preview requirements; do not recreate an existing pool of the same name.

```bash
az aks nodepool add -g "$BYOAKS_RESOURCE_GROUP" --cluster-name "$BYOAKS_CLUSTER" -n "$BYOAKS_KATA_POOL" \
  --os-sku AzureLinux --workload-runtime KataVmIsolation --node-vm-size "$BYOAKS_KATA_VM_SIZE" --node-count 1
```

**D2. Provision the binding from the approved sample directory.** Success means provision completes and foundry-system components become Ready; their count is not a success contract.

```bash
cd "$BYOAKS_SAMPLE_DIR"
azd config set auth.useAzCliAuth true
azd auth login
azd provision
az aks get-credentials -g "$BYOAKS_RESOURCE_GROUP" -n "$BYOAKS_CLUSTER" --overwrite-existing
kubectl get pods -n foundry-system
```

**D3. Configure the router network path only when needed.** The following subnet-NSG rule is the retained workshop recipe, not a universal production rule. Run it only if the product group confirms this ingress/source applies to your preview build and your subnet NSG blocks that route; otherwise use the approved network configuration.

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

**D4. Deploy and invoke the application.** These commands remain in the sample directory. Success: deployment completes, invoke answers, and show displays the endpoint. On failures inspect the sample/controller logs and the approved storage, identity and network settings; do not automatically purge resources.

```bash
azd deploy
azd ai agent invoke "Hi"
azd ai agent show
cd "$HOSTING_REPO"
```

**7. E — Deploy E2B Embed on an Azure VM.** Use an Ubuntu 24.04 LTS Gen2 VM that exposes `/dev/kvm` (such as `Standard_D4ds_v7`) and has Docker Engine 27+ with Compose 2.24+, with your user in the `docker` group ([E2B host requirements](https://github.com/e2b-dev/runtime/blob/588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/compose/README.md#requirements)). Restrict the E2B ports to your client CIDR in the subnet NSG. The Compose stack lives in `embed/compose/`, not in the repository root. On the VM (over SSH), download its two files from the measured commit `588e5b9`, check their SHA-256 against our run's record, and start the stack:

```bash
mkdir -p "$HOME/e2b" && cd "$HOME/e2b"
curl -fsSL --remote-name-all "https://raw.githubusercontent.com/e2b-dev/runtime/588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/compose/{compose.yaml,.env}"
printf '%s  %s\n' \
  658429e02665fa9e1cc23411e0897b1e2db1867e6fa9c47fb551ac5a313b6b74 compose.yaml \
  484510816c685a4d6d24bff34d00b05c46306146c0be397507dc215390a182fa .env \
  | sha256sum -c - && docker compose up -d --wait
```

Success: `sha256sum` prints `compose.yaml: OK` and `.env: OK`, then `docker compose up` exits 0, which it does only after the `base` template is built (time taken: the **Path setup in our run** row in [Results](#results); failures: [If `up` fails](https://github.com/e2b-dev/runtime/blob/588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/compose/README.md#if-up-fails)). If a hash differs, nothing starts; download the two files again.

Back in the shell you kept open in step 1, set `E2B_API_URL` and `E2B_SANDBOX_URL` in `.env` to the VM's address and reload it. Then install the E2B Python SDK version used in the measured run, `e2b==2.46.0`, which [the official Azure guide](https://github.com/e2b-dev/runtime/blob/588e5b9500b0987bc5a700d91483b03f0ae7d2a2/embed/terraform/azure/README.md?plain=1#L102) also pins (without the pin, `pip` installs the newest release: `2.56.0` on 2026-10-15, which needs Python 3.11+), and check the health endpoint:

```bash
cd "$HOSTING_REPO"
set -a && . "$HOSTING_REPO/.env" && set +a
python -m pip install e2b==2.46.0
curl --fail-with-body --show-error --max-time 30 "$E2B_API_URL/health"
```

Success: `/health` returns HTTP 200 with the body `Health check successful`.

**Done.** The selected path has an actual answering application and its usable entry, not merely a completed measurement command. Optional cold/warm tests, isolation checks and historical-number replay are in [VALIDATION.md](VALIDATION.md#tests-and-offline-checks).

**Offboard only after explicit owner approval; not part of deployment.** Each command below is its own block: run only the ones for resources you intend to remove. Stopping AKS saves compute charges, not all retained-resource charges.

Delete the A sandbox:

```bash
python tools/aca_sandbox.py delete
```

Stop the C cluster:

```bash
az aks stop -g "$RESOURCE_GROUP" -n "$AKS_NAME"
```

Stop the D cluster:

```bash
az aks stop -g "$BYOAKS_RESOURCE_GROUP" -n "$BYOAKS_CLUSTER"
```

Deallocate the E VM:

```bash
az vm deallocate -g "$E2B_RESOURCE_GROUP" -n "$E2B_VM_NAME"
```

Delete the resource group. This removes the shared foundation and A/B/C, and `az` asks you to confirm first:

```bash
az group delete -n "$RESOURCE_GROUP" --no-wait
```

**Repository.** [`tools/`](tools/) setup, measurement and checks · [`evidence/claims.json`](evidence/claims.json) canonical A–E claims · [`evidence/`](evidence/) redacted run records and `measurements.json` · [`images/`](images/) figures and icon ledger · [`config/`](config/) settings template · [`tests/`](tests/) offline tests (`python -m pytest -q`, run by CI on every push).
