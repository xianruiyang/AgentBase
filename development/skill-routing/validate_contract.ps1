param(
    [string]$ProjectRoot
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

function Assert-True {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

function Get-StringArray {
    param(
        [object]$Value
    )

    if ($null -eq $Value) {
        return @()
    }
    return @($Value | ForEach-Object { [string]$_ })
}

function Assert-Disjoint {
    param(
        [string[]]$Left,
        [string[]]$Right,
        [string]$Context
    )

    foreach ($item in $Left) {
        if ($Right -contains $item) {
            throw "$Context contains the same value in expected and forbidden sets: $item"
        }
    }
}

function Assert-MarkdownRelativeLinks {
    param(
        [string]$Path
    )

    $markdown = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $directory = Split-Path -Parent $Path
    foreach ($linkMatch in [regex]::Matches($markdown, '\[[^\]]+\]\((?<target>[^)]+)\)')) {
        $target = $linkMatch.Groups["target"].Value.Trim()
        if ($target.StartsWith("#") -or $target -match '^[a-zA-Z][a-zA-Z0-9+.-]*:') {
            continue
        }
        $targetPath = ($target -split '#', 2)[0].Trim('<', '>')
        if ([string]::IsNullOrWhiteSpace($targetPath)) {
            continue
        }
        $resolvedTarget = Join-Path $directory ([Uri]::UnescapeDataString($targetPath))
        Assert-True (Test-Path -LiteralPath $resolvedTarget) "Broken relative Markdown link in $Path`: $target"
    }
}

$contractPath = Join-Path $PSScriptRoot "trigger-cases.json"
$contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ($contract.schema_version -eq 3) "Unsupported trigger contract schema: $($contract.schema_version)"

$requiredSkills = @(Get-StringArray $contract.required_skills)
Assert-True ($requiredSkills.Count -gt 0) "Trigger contract has no required skills"
Assert-True (($requiredSkills | Sort-Object -Unique).Count -eq $requiredSkills.Count) "Trigger contract contains duplicate required skills"
$referenceEvaluationSkills = @(Get-StringArray $contract.reference_evaluation_skills)
Assert-True ($referenceEvaluationSkills.Count -gt 0) "Trigger contract has no conditional-reference skills"
Assert-True (($referenceEvaluationSkills | Sort-Object -Unique).Count -eq $referenceEvaluationSkills.Count) "Trigger contract contains duplicate conditional-reference skills"
foreach ($referenceSkill in $referenceEvaluationSkills) {
    Assert-True ($requiredSkills -contains $referenceSkill) "Conditional-reference skill is not in the required skill catalog: $referenceSkill"
}

$globalPath = Join-Path $ProjectRoot "global\AGENTS.md"
$globalItem = Get-Item -LiteralPath $globalPath
$globalContent = Get-Content -LiteralPath $globalPath -Raw -Encoding UTF8
Assert-True ($globalItem.Length -le [int]$contract.global_max_bytes) "Global AGENTS.md is $($globalItem.Length) bytes; contract limit is $($contract.global_max_bytes)"
$projectAgentsPath = Join-Path $ProjectRoot "AGENTS.md"
$projectAgentsItem = Get-Item -LiteralPath $projectAgentsPath
$projectAgentsContent = Get-Content -LiteralPath $projectAgentsPath -Raw -Encoding UTF8
$readmePath = Join-Path $ProjectRoot "README.md"
$readmeContent = Get-Content -LiteralPath $readmePath -Raw -Encoding UTF8
$planPath = Join-Path $ProjectRoot "docs\plan.md"
Assert-True (Test-Path -LiteralPath $planPath -PathType Leaf) "Project-wide plan entry is missing: docs/plan.md"
Assert-True ($readmeContent.Contains("docs/plan.md")) "README does not point to docs/plan.md"
Assert-True ($projectAgentsContent.Contains("docs/plan.md")) "Project AGENTS.md does not register docs/plan.md"
Assert-True ($projectAgentsContent.Contains("普通组件内任务不因本条加载总计划")) "Project AGENTS.md does not keep the project-wide plan conditional"
foreach ($ownerReadme in @(
    "global\README.md",
    "development\skill-routing\README.md",
    "development\plugin-packaging\README.md",
    "development\codex-deployment\README.md"
)) {
    $ownerReadmePath = Join-Path $ProjectRoot $ownerReadme
    Assert-True (Test-Path -LiteralPath $ownerReadmePath -PathType Leaf) "Component owner README is missing: $ownerReadme"
    Assert-True ($readmeContent.Contains($ownerReadme.Replace('\', '/'))) "Root README does not index component owner: $ownerReadme"
    Assert-MarkdownRelativeLinks -Path $ownerReadmePath
}
Assert-MarkdownRelativeLinks -Path $readmePath
Assert-MarkdownRelativeLinks -Path $planPath

$planContent = Get-Content -LiteralPath $planPath -Raw -Encoding UTF8
$subplanRows = @($planContent -split "`r?`n" | Where-Object { $_ -match '^\| [^|]+ \| \[[^]]+\]\(' })
$formalPlanTargets = @($subplanRows | ForEach-Object {
    $match = [regex]::Match($_, '^\| [^|]+ \| \[[^]]+\]\((?<target>[^)#]+)')
    if ($match.Success) { $match.Groups['target'].Value }
})
Assert-True (($formalPlanTargets | Sort-Object -Unique).Count -eq $formalPlanTargets.Count) "Project-wide plan assigns the same formal entry to multiple subplans"
$combinedInstructionBytes = $globalItem.Length + $projectAgentsItem.Length
Assert-True ($combinedInstructionBytes -le 28672) "AgentBase global and project AGENTS.md files use $combinedInstructionBytes bytes; keep at least 4 KiB below Codex's default 32 KiB project instruction limit"
Assert-True ($projectAgentsContent.Contains("本仓库文件本身不创建 Git 外部写授权")) "Project AGENTS.md must not treat repository text as self-granted Git external-write authorization"
Assert-True ($projectAgentsContent.Contains("用户针对该次发布的明确同意")) "Project AGENTS.md must require fresh user approval for every Codex Publish"

$requiredGlobalFragments = @(
    '`must` 表示必须执行'
    '`should` 表示默认执行'
    '`must not` 表示不得执行'
    '对象与范围更具体且不反转上位目标'
    '把用户表达视为共同理解目标的权威输入而非必然完整的目标'
    '规范来源只确定适用目标契约；有效证据才判断系统现状、原因、约束和结果'
    '系统事实不得静默改写目标或扩大授权'
    '不得为迎合而接受错误前提或弱化结论'
    '不创建替代目标或实施授权'
    '长期净收益和系统总成本'
    '只有方案必须新增或改变跨消费者长期行为时'
    '质量同等充分时再以较低上下文与 Token 成本为优'
    '不默认把实现限定为最窄局部补丁'
    '为使目标成立并接入唯一正式入口而必需'
    '仅改善架构而不影响本次结果的调整需另行授权'
    '长期收益不得作为扩大范围或替代用户裁决的理由'
    '不得仅凭自身声明创建外部写入、发布、凭据使用或高风险操作授权'
    '满足可用 skill 的 `description` 时使用该 skill'
    '`description` 同时定义触发与非触发边界'
    '内容仍需专业组织时'
    '默认属于长期资产'
    '仍须完成实施后的必要验收'
    '首次读取 skill 可例外使用一次精确路径'
    '模块测试只证模块契约'
    '原场景、同类变体和相近非触发场景'
    '长期资产还须接入正确职责和唯一正式入口'
    '沿实际依赖复核直接与间接消费者'
    '选择最低充分 next-turn 深度'
    '简单有界输出不建日志'
    '新一轮调试前只清理会干扰当前判断且目标范围明确的旧日志'
    '工作流程的目标、阶段、状态、依赖、完成和例外由文档定义'
    'CLI、脚本、索引、缓存和生成视图只辅助编辑、查询、压缩和机械校验'
    '全集、不存在或唯一结论先从最近项目正式来源确认权威源码范围，并只查询该范围'
    'PATH 中的 `srcq fd <fd argv...>`'
    '`srcq rg <rg argv...>`'
    '已知或唯一定位后按命中范围直接有界读取所缺正文且不再搜索重读'
    '文本不足才按需通过 srcq 升级 AST'
    '真实符号语义不足才用 LSP'
    '不预加载高级查询 skill 或工具说明'
    '证据充分即停止'
    '写错对象、破坏数据、并发覆盖、资源无界、缺少解释必需输入或混用查询快照'
    '其余可解析偏差只诊断'
)
foreach ($fragment in $requiredGlobalFragments) {
    Assert-True ($globalContent.Contains($fragment)) "Missing required global contract fragment: $fragment"
}

$invalidRuleLines = Get-Content -LiteralPath $globalPath -Encoding UTF8 |
    Where-Object { $_ -match '^(must|should|may)' -and $_ -notmatch '^(must not|must|should):' }
Assert-True (@($invalidRuleLines).Count -eq 0) "Global AGENTS.md contains a malformed normative rule label"

$duplicateRules = Get-Content -LiteralPath $globalPath -Encoding UTF8 |
    Where-Object { $_ -match '^(must|should|must not):' } |
    Group-Object |
    Where-Object { $_.Count -gt 1 }
Assert-True (@($duplicateRules).Count -eq 0) "Global AGENTS.md contains duplicate normative rules"

$descriptionBoundaryFragments = @{
    "source-query" = "分页或截断确实阻止当前必要证据"
    "change-governance" = "不用于规格已完整"
    "codex-event-logger" = "当前上下文充分"
    "codex-qq-hook" = "状态查询不得创建或改写配置"
    "delivery-workflow" = "不用于规格已完整的单轮实现"
    "powershell-usage" = "不用于单条精确只读"
    "reasoning-governor" = "没有 active Goal 时不用于模型自主切换"
    "symbol-structure-workflow" = "不用于只读文本"
    "task-table-manager" = "不用于单轮修改"
    "understand-space" = "不因正文偶然出现空间词触发"
}

foreach ($skill in $requiredSkills) {
    $skillRoot = Join-Path (Join-Path $ProjectRoot "skills") $skill
    $skillPath = Join-Path $skillRoot "SKILL.md"
    $metadataPath = Join-Path $skillRoot "agents\openai.yaml"
    Assert-True (Test-Path -LiteralPath $skillPath -PathType Leaf) "Missing SKILL.md for required skill: $skill"
    Assert-True (Test-Path -LiteralPath $metadataPath -PathType Leaf) "Missing agents/openai.yaml for required skill: $skill"

    $skillItem = Get-Item -LiteralPath $skillPath
    Assert-True ($skillItem.Length -le [int]$contract.skill_main_max_bytes) "SKILL.md for $skill is $($skillItem.Length) bytes; main-skill limit is $($contract.skill_main_max_bytes)"
    $skillContent = Get-Content -LiteralPath $skillPath -Raw -Encoding UTF8
    $frontmatterMatch = [regex]::Match($skillContent, '(?s)\A---\r?\n(?<frontmatter>.*?)\r?\n---')
    Assert-True $frontmatterMatch.Success "Invalid or missing frontmatter in skill: $skill"
    $frontmatter = $frontmatterMatch.Groups["frontmatter"].Value
    $nameMatch = [regex]::Match($frontmatter, '(?m)^name:\s*(?<name>[^\r\n]+)\s*$')
    $descriptionMatch = [regex]::Match($frontmatter, '(?m)^description:\s*(?<description>.+?)\s*$')
    Assert-True ($nameMatch.Success -and $nameMatch.Groups["name"].Value.Trim('"') -eq $skill) "Skill name does not match folder: $skill"
    Assert-True ($descriptionMatch.Success -and -not [string]::IsNullOrWhiteSpace($descriptionMatch.Groups["description"].Value)) "Missing skill description: $skill"

    if ($descriptionBoundaryFragments.ContainsKey($skill)) {
        Assert-True ($descriptionMatch.Groups["description"].Value.Contains($descriptionBoundaryFragments[$skill])) "Skill description is missing its non-trigger boundary: $skill"
    }

    $rootMarkdown = @(Get-ChildItem -LiteralPath $skillRoot -File -Filter "*.md")
    $unexpectedRootMarkdown = @($rootMarkdown | Where-Object { $_.Name -ne "SKILL.md" })
    Assert-True ($unexpectedRootMarkdown.Count -eq 0) "Skill root contains auxiliary Markdown outside SKILL.md: $skill"

    $referenceRoot = Join-Path $skillRoot "references"
    if (Test-Path -LiteralPath $referenceRoot -PathType Container) {
        foreach ($referenceFile in @(Get-ChildItem -LiteralPath $referenceRoot -File -Filter "*.md")) {
            $relativeTarget = "references/$($referenceFile.Name)"
            Assert-True ($skillContent.Contains("]($relativeTarget)")) "Skill reference is not linked directly from SKILL.md: $skill/$relativeTarget"
            $referenceLines = @(Get-Content -LiteralPath $referenceFile.FullName -Encoding UTF8)
            if ($referenceLines.Count -gt 100) {
                $referenceContent = $referenceLines -join [Environment]::NewLine
                Assert-True ($referenceContent -match '(?m)^## 目录\s*$') "Skill reference longer than 100 lines is missing a table of contents: $skill/$relativeTarget"
            }
        }
    }

    $metadata = Get-Content -LiteralPath $metadataPath -Raw -Encoding UTF8
    $displayMatch = [regex]::Match($metadata, '(?m)^\s{2}display_name:\s*"(?<value>[^"]+)"\s*$')
    $shortMatch = [regex]::Match($metadata, '(?m)^\s{2}short_description:\s*"(?<value>[^"]+)"\s*$')
    $promptMatch = [regex]::Match($metadata, '(?m)^\s{2}default_prompt:\s*"(?<value>[^"]+)"\s*$')
    Assert-True $displayMatch.Success "Missing quoted interface.display_name in agents/openai.yaml: $skill"
    Assert-True $shortMatch.Success "Missing quoted interface.short_description in agents/openai.yaml: $skill"
    Assert-True $promptMatch.Success "Missing quoted interface.default_prompt in agents/openai.yaml: $skill"
    $shortLength = $shortMatch.Groups["value"].Value.Length
    Assert-True ($shortLength -ge 25 -and $shortLength -le 64) "short_description for $skill must be 25-64 characters; got $shortLength"
    Assert-True ($promptMatch.Groups["value"].Value.Contains('$' + $skill)) "default_prompt must explicitly reference the skill token: $skill"
}

$sourceQueryRoot = Join-Path $ProjectRoot "skills\source-query"
$sourceQueryContent = Get-Content -LiteralPath (Join-Path $sourceQueryRoot "SKILL.md") -Raw -Encoding UTF8
$sourceQueryAstContent = Get-Content -LiteralPath (Join-Path $sourceQueryRoot "references\ast.md") -Raw -Encoding UTF8
$sourceQueryLspContent = Get-Content -LiteralPath (Join-Path $sourceQueryRoot "references\lsp.md") -Raw -Encoding UTF8
$symbolSkillContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\symbol-structure-workflow\SKILL.md") -Raw -Encoding UTF8
Assert-True ($sourceQueryContent.Contains('PATH 中的 `srcq.exe`')) "source-query must use the installed PATH runtime"
Assert-True ($sourceQueryContent.Contains('不搜索项目构建目录、Skill、插件或 Codex 缓存中的私有副本')) "source-query must not discover private runtime copies"
Assert-True ($sourceQueryContent.Contains('只读取当前缺口对应的引用')) "source-query must load only the reference needed by the current gap"
Assert-True ($sourceQueryContent.Contains('证据充分即停止')) "source-query must stop when evidence is sufficient"
Assert-True ($sourceQueryContent.Contains('续页沿用同一 snapshot 和精确 cursor')) "source-query must preserve continuation identity"
Assert-True ($globalContent.Contains('PATH 中的 `srcq fd <fd argv...>`')) "global rules must expose the minimal direct fd syntax"
Assert-True ($globalContent.Contains('`srcq rg <rg argv...>`')) "global rules must expose the minimal direct rg syntax"
Assert-True ($sourceQueryAstContent.Contains('“完整定义”是验收结果，不是 AST 触发词')) "source-query must not trigger AST from the requested result wording alone"
Assert-True ($sourceQueryAstContent.Contains('无匹配不是继续猜 pattern 的依据')) "source-query must require new source evidence before another AST pattern"
Assert-True ($sourceQueryAstContent.Contains('`_sgy.total/files/shown/omitted/complete/cache`')) "source-query must preserve the stable AST result protocol"
Assert-True ($sourceQueryLspContent.Contains('单根工作区的 `file` 使用根相对路径')) "source-query must distinguish single-root logical paths"
Assert-True ($sourceQueryLspContent.Contains('多根才使用 `<root-alias>/<relative-path>`')) "source-query must distinguish multi-root logical paths"
Assert-True ($sourceQueryLspContent.Contains('在小项目、热索引或高效 Provider 下可以直接使用')) "source-query must keep workspace_symbols conditionally available"
Assert-True ($symbolSkillContent.Contains('这些由 source-query 承担')) "symbol-structure-workflow must delegate read-only source queries"

$routingCommonPath = Join-Path $PSScriptRoot "routing_evaluation_common.ps1"
$routingCommonContent = Get-Content -LiteralPath $routingCommonPath -Raw -Encoding UTF8
Assert-True (-not ($routingCommonContent -match 'Get-ChildItem[^\r\n]+-Recurse')) "Routing evaluation must not collect recursive skill artifacts"
Assert-True ($routingCommonContent.Contains('"SKILL.md"')) "Routing evaluation must bind each evaluated SKILL.md"
Assert-True ($routingCommonContent.Contains('"agents\openai.yaml"')) "Routing evaluation must bind each evaluated agents/openai.yaml"
Assert-True ($routingCommonContent.Contains('detached capsule')) "Routing evaluation must declare its detached-capsule boundary"
foreach ($routingScriptName in @("build_routing_evaluation.ps1", "validate_routing_results.ps1")) {
    $routingScriptContent = Get-Content -LiteralPath (Join-Path $PSScriptRoot $routingScriptName) -Raw -Encoding UTF8
    Assert-True ($routingScriptContent.Contains('routing_evaluation_common.ps1')) "$routingScriptName must use the canonical detached-capsule implementation"
}
Assert-True ($routingCommonContent.Contains('The skill catalog intentionally exposes descriptions only')) "Routing evaluation does not preserve the pre-selection description-only boundary"
Assert-True ($routingCommonContent.Contains('Policy labels, post-selection skill bodies, and reference choices are intentionally unavailable in this stage')) "Routing evaluation exposes post-routing policy hints during first-stage skill selection"
Assert-True ($routingCommonContent.Contains('evaluation_kind = "behavior-policy"')) "Routing evaluation is missing its post-routing behavior-policy phase"
Assert-True ($routingCommonContent.Contains('routing-reference-policy')) "Routing evaluation is missing its post-selection change-governance reference phase"
Assert-True (Test-Path -LiteralPath (Join-Path $PSScriptRoot "merge_routing_evidence.ps1") -PathType Leaf) "Routing evaluation is missing its canonical staged evidence merge entry"

$governorSkillPath = Join-Path $ProjectRoot "skills\reasoning-governor\SKILL.md"
$governorScriptPath = Join-Path $ProjectRoot "skills\reasoning-governor\scripts\reasoning-governor.mjs"
$governorSkillContent = Get-Content -LiteralPath $governorSkillPath -Raw -Encoding UTF8
$governorScriptContent = Get-Content -LiteralPath $governorScriptPath -Raw -Encoding UTF8
Assert-True ($governorSkillContent.Contains('不使用 `Stop` hook')) "reasoning-governor must keep Stop hooks outside its continuation contract"
Assert-True ($governorSkillContent.Contains("不保存 pending、previous effort 或自动恢复状态")) "reasoning-governor must not create a second reasoning state source"
Assert-True ($governorScriptContent.Contains('args.action === "status"')) "reasoning-governor script is missing its read-only status operation"
Assert-True ($governorScriptContent.Contains('operation: "set"')) "reasoning-governor script is missing its set receipt contract"

$taskTableSkillPath = Join-Path $ProjectRoot "skills\task-table-manager\SKILL.md"
$taskTableSkillContent = Get-Content -LiteralPath $taskTableSkillPath -Raw -Encoding UTF8
Assert-True ($taskTableSkillContent.Contains('`$reasoning-governor`')) "task-table-manager must delegate reasoning depth to reasoning-governor"
$taskTableScriptPath = Join-Path $ProjectRoot "skills\task-table-manager\scripts\taskctl.py"
$taskTableScriptContent = Get-Content -LiteralPath $taskTableScriptPath -Raw -Encoding UTF8
Assert-True ($taskTableSkillContent.Contains('任务表文档是执行投影，不是计划正确性的裁判')) "task-table-manager does not declare its assistive responsibility"
Assert-True ($taskTableSkillContent.Contains('最终完成标准只来自 `$delivery-workflow` 当前执行周期经用户确认的需求与用户设计')) "task-table-manager does not delegate final completion to the user-confirmed document scope"
Assert-True ($taskTableSkillContent.Contains('`taskctl` 只辅助存储、索引、查询、上下文压缩和可重建视图')) "task-table-manager does not keep taskctl assistive"
Assert-True ($taskTableSkillContent.Contains('优先继续当前目标链并缩短到最近可验证闭环的距离')) "task-table-manager is missing vertical validation closure selection"
Assert-True ($taskTableScriptContent.Contains('command_completion_context')) "taskctl is missing its bounded final-review context"
Assert-True ($taskTableScriptContent.Contains('needs_review_count')) "taskctl status does not expose the review count"
Assert-True ($taskTableScriptContent.Contains('upstream_index_derived_content_mismatch')) "taskctl does not bind cached index content to current workflow documents"
Assert-True ($taskTableScriptContent.Contains('completion snapshot changed')) "taskctl completion pagination is missing snapshot consistency"
Assert-True ($taskTableScriptContent.Contains('TASK-PAGINATION-SNAPSHOT')) "taskctl completion snapshot gate is not structured"
Assert-True ($taskTableScriptContent.Contains('owner_mismatch')) "taskctl does not report owner conflicts as diagnostics"
Assert-True ($taskTableScriptContent.Contains('dependency_cycle')) "taskctl does not report dependency cycles as diagnostics"
Assert-True ($taskTableScriptContent.Contains('source_snapshot')) "taskctl results do not bind evidence to upstream source snapshots"
Assert-True ($taskTableScriptContent.Contains('result_source_snapshot_missing')) "taskctl does not diagnose results without an execution-time source snapshot"
Assert-True ($taskTableScriptContent.Contains('result_source_snapshot_incomplete')) "taskctl does not diagnose incomplete transitive source snapshots"
Assert-True ($taskTableScriptContent.Contains('source_snapshot_complete')) "taskctl context does not expose source snapshot completeness"
Assert-True ($taskTableScriptContent.Contains('"path": path')) "taskctl dependent queries do not expose a traceable consumption path"
Assert-True ($taskTableScriptContent.Contains('"retired"')) "taskctl is missing retired task state support"
Assert-True ($taskTableScriptContent.Contains('non_standard_status')) "taskctl does not preserve non-standard states as diagnostics"
Assert-True ($taskTableScriptContent.Contains('non_standard_dependency_type')) "taskctl does not preserve non-standard dependency semantics as diagnostics"
Assert-True ($taskTableScriptContent.Contains('result_history_record_unreadable')) "taskctl does not isolate damaged historical results"
Assert-True ($taskTableScriptContent.Contains('[*task["source_ids"], *evidence_for]')) "taskctl completion context does not consume direct result evidence mappings"
Assert-True (-not $taskTableScriptContent.Contains('contains duplicate values')) "taskctl still blocks parseable duplicate values"
Assert-True (-not $taskTableScriptContent.Contains('choices=STATUSES')) "taskctl still uses its status vocabulary as an argparse gate"
Assert-True (Test-Path -LiteralPath (Join-Path $ProjectRoot "skills\task-table-manager\tests\test_taskctl.py") -PathType Leaf) "task-table-manager is missing its CLI regression tests"

$deliveryRoot = Join-Path $ProjectRoot "skills\delivery-workflow"
$deliverySkillContent = Get-Content -LiteralPath (Join-Path $deliveryRoot "SKILL.md") -Raw -Encoding UTF8
$deliveryScriptContent = Get-Content -LiteralPath (Join-Path $deliveryRoot "scripts\workctl.py") -Raw -Encoding UTF8
$deliveryReferenceRoot = Join-Path $deliveryRoot "references"
$deliveryCommonContractPath = Join-Path $deliveryReferenceRoot "artifact-contracts.md"
$deliveryTargetContractPath = Join-Path $deliveryReferenceRoot "target-contracts.md"
$deliveryPlanningContractPath = Join-Path $deliveryReferenceRoot "planning-contracts.md"
$deliveryExecutionContractPath = Join-Path $deliveryReferenceRoot "execution-contracts.md"
$deliveryIterationPath = Join-Path $deliveryReferenceRoot "iteration.md"
foreach ($deliveryContractPath in @($deliveryCommonContractPath, $deliveryTargetContractPath, $deliveryPlanningContractPath, $deliveryExecutionContractPath, $deliveryIterationPath)) {
    Assert-True (Test-Path -LiteralPath $deliveryContractPath -PathType Leaf) "delivery-workflow is missing a routed contract: $deliveryContractPath"
}
$deliveryCommonContractContent = Get-Content -LiteralPath $deliveryCommonContractPath -Raw -Encoding UTF8
$deliveryTargetContractContent = Get-Content -LiteralPath $deliveryTargetContractPath -Raw -Encoding UTF8
$deliveryPlanningContractContent = Get-Content -LiteralPath $deliveryPlanningContractPath -Raw -Encoding UTF8
$deliveryExecutionContractContent = Get-Content -LiteralPath $deliveryExecutionContractPath -Raw -Encoding UTF8
$deliveryIterationContent = Get-Content -LiteralPath $deliveryIterationPath -Raw -Encoding UTF8
Assert-True ($deliverySkillContent.Contains('requirements.md') -and $deliverySkillContent.Contains('user-design.md')) "delivery-workflow does not separate protected user sources"
Assert-True ($deliverySkillContent.Contains('模型设计、分析、方案、任务状态、快照、索引、结构检查和各阶段审核都只是中间结果')) "delivery-workflow does not limit intermediate reviews"
Assert-True ($deliverySkillContent.Contains('Markdown 阶段文档是语义真源')) "delivery-workflow does not keep documents authoritative"
Assert-True ($deliverySkillContent.Contains('当前消费者接入')) "delivery-workflow does not close shared responsibilities through current consumers"
Assert-True ($deliverySkillContent.Contains('只增加当前动作所属的一项')) "delivery-workflow does not progressively route stage contracts"
Assert-True ($deliverySkillContent.Contains('target-contracts.md') -and $deliverySkillContent.Contains('planning-contracts.md') -and $deliverySkillContent.Contains('execution-contracts.md')) "delivery-workflow main entry does not route every stage owner"
Assert-True ($deliveryTargetContractContent.Contains('## 需求分析') -and $deliveryTargetContractContent.Contains('## 用户设计') -and $deliveryTargetContractContent.Contains('## 延后讨论项')) "delivery-workflow protected-target contract is incomplete"
Assert-True ($deliveryPlanningContractContent.Contains('## 模型设计') -and $deliveryPlanningContractContent.Contains('## 现状分析') -and $deliveryPlanningContractContent.Contains('## 方案设计')) "delivery-workflow planning contract is incomplete"
Assert-True ($deliveryExecutionContractContent.Contains('## 任务与结果') -and $deliveryExecutionContractContent.Contains('## 最终完成合同')) "delivery-workflow execution contract is incomplete"
Assert-True ($deliveryIterationContent.Contains('## 执行上下文') -and $deliveryIterationContent.Contains('默认形成以下最小语义闭包')) "delivery-workflow does not define the minimum semantic execution closure"
Assert-True ($deliveryIterationContent.Contains('目标或来源仍有歧义') -and $deliveryIterationContent.Contains('实际消费者、派生产物或旧路径需要影响传播') -and $deliveryIterationContent.Contains('进入最终完成复核')) "delivery-workflow does not define evidence-driven context expansion"
Assert-True ($deliveryScriptContent.Contains('delivery.protected-baseline')) "workctl is missing protected baseline support"
Assert-True ($deliveryScriptContent.Contains('baseline_source_drift')) "workctl does not report protected-source drift as a diagnostic"
Assert-True ($deliveryScriptContent.Contains('exclusive_write_json')) "workctl protected baseline is not created exclusively"
Assert-True ($deliveryScriptContent.Contains('baseline_has_no_final_target')) "workctl does not diagnose a snapshot without final targets"
Assert-True ($deliveryScriptContent.Contains('WORK-SNAPSHOT-RACE')) "workctl snapshot-race gate is not structured"
Assert-True ($deliveryScriptContent.Contains('history')) "workctl does not preserve prior confirmation snapshots for new cycles"
Assert-True ($deliveryScriptContent.Contains('"path": paths[section_id]')) "workctl impact does not expose a traceable semantic path"
Assert-True (Test-Path -LiteralPath (Join-Path $deliveryRoot "tests\test_workctl.py") -PathType Leaf) "delivery-workflow is missing its CLI regression tests"

$taskDeliveryMarkdown = @(
    Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "skills\task-table-manager") -Recurse -File -Filter "*.md"
    Get-ChildItem -LiteralPath $deliveryRoot -Recurse -File -Filter "*.md"
)
foreach ($formalFile in $taskDeliveryMarkdown) {
    $formalContent = Get-Content -LiteralPath $formalFile.FullName -Raw -Encoding UTF8
    foreach ($removedConcept in @('strict_v2', 'semantic_preflight', 'legacy_', 'Legacy：', '旧版兼容', 'v1 计划')) {
        Assert-True (-not $formalContent.Contains($removedConcept)) "Removed task mechanism appears in formal content: $($formalFile.FullName): $removedConcept"
    }
}

$qqSwitchPath = Join-Path $ProjectRoot "skills\codex-qq-hook\scripts\qq_hook_switch.ps1"
$qqSwitchContent = Get-Content -LiteralPath $qqSwitchPath -Raw -Encoding UTF8
$qqStatusIndex = $qqSwitchContent.IndexOf('if ($Action -eq "status")', [StringComparison]::Ordinal)
$qqDirectoryWriteIndex = $qqSwitchContent.IndexOf('New-Item -ItemType Directory', [StringComparison]::Ordinal)
$qqFileWriteIndex = $qqSwitchContent.IndexOf('Set-Content -LiteralPath $ConfigPath', [StringComparison]::Ordinal)
Assert-True ($qqStatusIndex -ge 0) "codex-qq-hook switch is missing its status branch"
Assert-True ($qqDirectoryWriteIndex -gt $qqStatusIndex) "codex-qq-hook status must return before directory creation"
Assert-True ($qqFileWriteIndex -gt $qqStatusIndex) "codex-qq-hook status must return before file writes"
Assert-True (-not $qqSwitchContent.Contains('default-on')) "codex-qq-hook exposes an undocumented default-on mutation"
Assert-True (-not $qqSwitchContent.Contains('default-off')) "codex-qq-hook exposes an undocumented default-off mutation"
Assert-True (Test-Path -LiteralPath (Join-Path $ProjectRoot "skills\codex-qq-hook\tests\test_qq_hook_switch.ps1") -PathType Leaf) "codex-qq-hook is missing its switch regression test"
$qqDirectScriptPath = Join-Path $ProjectRoot "skills\codex-qq-hook\scripts\send_qq_message.ps1"
$qqDirectScriptContent = Get-Content -LiteralPath $qqDirectScriptPath -Raw -Encoding UTF8
$qqTransportContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\codex-qq-hook\scripts\codex_qq_notify.py") -Raw -Encoding UTF8
$qqRuntimePath = Join-Path $ProjectRoot "skills\codex-qq-hook\scripts\qq_notify_runtime.ps1"
$qqGlobalTemplateContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\codex-qq-hook\templates\qq-hook-global-settings.template.json") -Raw -Encoding UTF8
Assert-True (Test-Path -LiteralPath $qqDirectScriptPath -PathType Leaf) "codex-qq-hook is missing its direct message entry"
Assert-True (Test-Path -LiteralPath $qqRuntimePath -PathType Leaf) "codex-qq-hook is missing its shared notification runtime"
Assert-True ($qqDirectScriptContent.Contains('QQ_BOT_DIRECT_SEND_AUTHORIZED')) "codex-qq-hook direct entry does not bind transport authorization"
Assert-True ($qqDirectScriptContent.Contains('send requires a non-sensitive -Reason')) "codex-qq-hook direct entry does not require an audit reason"
Assert-True ($qqTransportContent.Contains('direct sending requires the authorized wrapper')) "codex-qq-hook transport exposes a parallel direct-send entry"
Assert-True ($qqGlobalTemplateContent.Contains('"direct_send"') -and $qqGlobalTemplateContent.Contains('"enabled": false')) "codex-qq-hook direct sending must default off"
Assert-True (Test-Path -LiteralPath (Join-Path $ProjectRoot "skills\codex-qq-hook\tests\test_send_qq_message.ps1") -PathType Leaf) "codex-qq-hook is missing its direct message regression test"

$eventLoggerRoot = Join-Path $ProjectRoot "skills\codex-event-logger"
$eventLoggerSkillContent = Get-Content -LiteralPath (Join-Path $eventLoggerRoot "SKILL.md") -Raw -Encoding UTF8
$eventLoggerReaderPath = Join-Path $eventLoggerRoot "scripts\read_codex_turn_log.py"
Assert-True (-not (Test-Path -LiteralPath (Join-Path $eventLoggerRoot "HOOK_INSTALL.md"))) "codex-event-logger keeps installation documentation inside the skill root"
Assert-True (Test-Path -LiteralPath $eventLoggerReaderPath -PathType Leaf) "codex-event-logger is missing its bounded reader"
Assert-True ($eventLoggerSkillContent.Contains('read_codex_turn_log.py')) "codex-event-logger SKILL.md does not route reads through the bounded reader"
Assert-True (-not $eventLoggerSkillContent.Contains('Get-Content -Raw')) "codex-event-logger SKILL.md contains an unbounded raw read"
Assert-True (Test-Path -LiteralPath (Join-Path $eventLoggerRoot "tests\test_event_logger.py") -PathType Leaf) "codex-event-logger is missing its regression tests"

$expectedSourceQueryFiles = @(
    'SKILL.md',
    'agents\openai.yaml',
    'references\ast.md',
    'references\lsp.md',
    'references\rg-fd.md'
)
$actualSourceQueryFiles = @(Get-ChildItem -LiteralPath $sourceQueryRoot -Recurse -File | ForEach-Object {
    $_.FullName.Substring($sourceQueryRoot.Length + 1)
})
Assert-True ($actualSourceQueryFiles.Count -eq $expectedSourceQueryFiles.Count) "source-query payload must contain only its five protocol files"
foreach ($relativePath in $expectedSourceQueryFiles) {
    Assert-True ($actualSourceQueryFiles -contains $relativePath) "source-query payload is missing $relativePath"
}
foreach ($retiredSkill in @('ast-grep-token-safe', 'fd-usage', 'rg-token-safe')) {
    $retiredSkillEntry = Join-Path (Join-Path (Join-Path $ProjectRoot 'skills') $retiredSkill) 'SKILL.md'
    Assert-True (-not (Test-Path -LiteralPath $retiredSkillEntry -PathType Leaf)) "Retired query skill is still a formal entry: $retiredSkill"
}
$srcqRoot = Join-Path $ProjectRoot 'tools\srcq'
Assert-True (Test-Path -LiteralPath (Join-Path $srcqRoot 'Cargo.toml') -PathType Leaf) "srcq source package is missing"
Assert-True (Test-Path -LiteralPath (Join-Path $srcqRoot 'scripts\install-srcq.ps1') -PathType Leaf) "srcq lifecycle installer is missing"

$powerShellSkillContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\powershell-usage\SKILL.md") -Raw -Encoding UTF8
Assert-True ($powerShellSkillContent.Contains('PowerShell 7（`pwsh`）')) "powershell-usage does not declare its PowerShell 7 baseline"
Assert-True ($powerShellSkillContent.Contains('普通任务不重复探测版本')) "powershell-usage does not delegate host verification to environment initialization"
Assert-True (-not $powerShellSkillContent.Contains('$PSVersionTable.PSVersion')) "powershell-usage performs redundant per-command host version detection"
Assert-True (-not $powerShellSkillContent.Contains('Windows PowerShell 5.1')) "powershell-usage keeps obsolete Windows PowerShell 5.1 guidance"

$symbolMetadataPath = Join-Path $ProjectRoot "skills\symbol-structure-workflow\agents\openai.yaml"
$symbolMetadata = Get-Content -LiteralPath $symbolMetadataPath -Raw -Encoding UTF8
Assert-True ($symbolMetadata -match '(?m)^\s{4}- type:\s*"mcp"\s*$') "symbol-structure-workflow must declare an MCP tool dependency"
Assert-True ($symbolMetadata -match '(?m)^\s{6}value:\s*"vscode-lsp-mcp"\s*$') "symbol-structure-workflow MCP dependency must target vscode-lsp-mcp"
$sourceQueryMetadata = Get-Content -LiteralPath (Join-Path $sourceQueryRoot 'agents\openai.yaml') -Raw -Encoding UTF8
Assert-True ($sourceQueryMetadata -match '(?m)^\s{4}- type:\s*"mcp"\s*$') "source-query must declare an MCP tool dependency"
Assert-True ($sourceQueryMetadata -match '(?m)^\s{6}value:\s*"vscode-lsp-mcp"\s*$') "source-query MCP dependency must target vscode-lsp-mcp"

$spaceSkillContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\understand-space\SKILL.md") -Raw -Encoding UTF8
$spaceTransformReference = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\understand-space\references\frame-transform-verification.md") -Raw -Encoding UTF8
Assert-True ($spaceTransformReference.Contains("齐次坐标列向量、变换左乘")) "understand-space must declare the convention used by its transform formulas"
Assert-True ($spaceSkillContent.Contains("不能直接套用公式") -or $spaceTransformReference.Contains("不能直接套用公式")) "understand-space must require API-specific convention mapping"

$qqResolverPath = Join-Path $ProjectRoot "skills\codex-qq-hook\scripts\resolve_codex_home.ps1"
$qqStopScriptContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\codex-qq-hook\scripts\codex_stop_qq_notify.ps1") -Raw -Encoding UTF8
$qqInstallerContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\codex-qq-hook\scripts\install_global_qq_hook.ps1") -Raw -Encoding UTF8
Assert-True (Test-Path -LiteralPath $qqResolverPath -PathType Leaf) "codex-qq-hook is missing its location-independent Codex root resolver"
Assert-True ($qqStopScriptContent.Contains("Resolve-AgentBaseCodexHome")) "codex-qq-hook Stop handler still derives Codex root from its installation path"
Assert-True ($qqStopScriptContent.Contains('qq_notify_runtime.ps1') -and $qqDirectScriptContent.Contains('qq_notify_runtime.ps1')) "QQ Hook and direct sending do not share configuration loading"
Assert-True ($qqInstallerContent.Contains('[string]$CodexRoot')) "codex-qq-hook installer must accept an explicit Codex root"

$allMarkdownFiles = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "skills") -Recurse -File -Filter "*.md"
foreach ($markdownFile in $allMarkdownFiles) {
    Assert-MarkdownRelativeLinks -Path $markdownFile.FullName
}

$workflowPath = Join-Path $ProjectRoot ".github\workflows\validate.yml"
$workflowContent = Get-Content -LiteralPath $workflowPath -Raw -Encoding UTF8
Assert-True ($workflowContent.Contains("npm run verify:release")) "Repository CI does not run the vscode-lsp-mcp release gate"
Assert-True ($workflowContent.Contains("rustsec/audit-check@")) "Repository CI does not run the RustSec gate"
Assert-True ($workflowContent.Contains("srcq-windows:")) "Repository CI is missing the Windows srcq native gate"
Assert-True ($workflowContent.Contains("validate_routing_results.ps1") -and $workflowContent.Contains("evidence\current.json")) "Repository CI does not validate current routing-policy evidence"
Assert-True ($workflowContent.Contains("test_routing_fingerprint.ps1")) "Repository CI does not verify line-ending-neutral routing fingerprints"
Assert-True ($workflowContent.Contains("test_routing_capsule.ps1")) "Repository CI does not verify the detached routing capsule boundary"
Assert-True ($workflowContent.Contains("test_send_qq_message.ps1")) "Repository CI does not run the direct QQ message regression test"
Assert-True ($workflowContent.Contains("build_plugin.ps1") -and $workflowContent.Contains("-SkipOfficialValidation")) "Repository CI does not build the plugin package with its portable contract"
$unpinnedActions = @([regex]::Matches($workflowContent, '(?m)^\s*-?\s*uses:\s*[^@\s]+@(?<ref>[^\s#]+)') | Where-Object {
    $_.Groups["ref"].Value -notmatch '^[0-9a-f]{40}$'
})
Assert-True ($unpinnedActions.Count -eq 0) "Repository CI contains an action that is not pinned to a full commit SHA"

$payloadContractPath = Join-Path $ProjectRoot "development\common\payload_contract.ps1"
$pluginBuilderPath = Join-Path $ProjectRoot "development\plugin-packaging\build_plugin.ps1"
$pluginBuilderContent = Get-Content -LiteralPath $pluginBuilderPath -Raw -Encoding UTF8
Assert-True (Test-Path -LiteralPath $payloadContractPath -PathType Leaf) "Shared deployable payload contract is missing"
Assert-True ($pluginBuilderContent.Contains("Copy-AgentBasePayloadDirectory")) "Plugin builder does not use the shared deployable payload filter"
Assert-True ($pluginBuilderContent.Contains("official_plugin_validation")) "Plugin build manifest does not disclose whether the official validator ran"
Assert-True (-not ($pluginBuilderContent -match 'Copy-Item\s+-LiteralPath\s+\$sourceSkill[^\r\n]+-Recurse')) "Plugin builder recursively copies unfiltered skill sources"
$pluginHooksPath = Join-Path $ProjectRoot "development\plugin-packaging\template\agentbase-core\hooks\hooks.json"
$pluginHooksContent = Get-Content -LiteralPath $pluginHooksPath -Raw -Encoding UTF8
$null = $pluginHooksContent | ConvertFrom-Json
Assert-True ($pluginHooksContent.Contains('${PLUGIN_ROOT}\\skills\\codex-event-logger')) "Plugin hooks do not locate event logger through PLUGIN_ROOT"
Assert-True ($pluginHooksContent.Contains('${PLUGIN_ROOT}\\skills\\codex-qq-hook')) "Plugin hooks do not locate QQ hook through PLUGIN_ROOT"
$marketplacePath = Join-Path $ProjectRoot ".agents\plugins\marketplace.json"
$marketplace = Get-Content -LiteralPath $marketplacePath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ([string]$marketplace.name -eq "agentbase-local") "Repo marketplace has the wrong identity"
Assert-True (@($marketplace.plugins).Count -eq 1 -and [string]$marketplace.plugins[0].source.path -eq "./development/plugin-packaging/dist/agentbase-core") "Repo marketplace does not point at the generated AgentBase plugin"

$lifecyclePath = Join-Path $ProjectRoot "skills\change-governance\references\lifecycle-and-entry.md"
$lifecycleContent = Get-Content -LiteralPath $lifecyclePath -Raw -Encoding UTF8
Assert-True ($lifecycleContent.Contains("优先更新已经承担相应规范职责的文档、配置或接口")) "Lifecycle reference is missing authority-carrier synchronization"
Assert-True ($lifecycleContent.Contains("按稳定约束、状态与生命周期、失败或持久化边界以及变化原因判断职责是否相同")) "Lifecycle reference is missing semantic shared-responsibility criteria"
Assert-True ($lifecycleContent.Contains("每个适用下游必须形成可恢复的持久裁决")) "Lifecycle reference is missing downstream impact closure"
$responsibilityDesignPath = Join-Path $ProjectRoot "development\responsibility-lifecycle.md"
Assert-True (Test-Path -LiteralPath $responsibilityDesignPath -PathType Leaf) "Responsibility lifecycle design analysis is missing"
Assert-True ($projectAgentsContent.Length -gt 0 -and $readmeContent.Contains("development/responsibility-lifecycle.md")) "README does not index the responsibility lifecycle design analysis"
$changeSkillContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\change-governance\SKILL.md") -Raw -Encoding UTF8
Assert-True ($changeSkillContent.Contains("多个入口或第二状态源的方案裁决")) "change-governance does not expose its multi-entry decision trigger"
Assert-True ($changeSkillContent.Contains("临时路径风险评审")) "change-governance does not expose its temporary-path review trigger"
$qqSkillContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\codex-qq-hook\SKILL.md") -Raw -Encoding UTF8
Assert-True ($qqSkillContent.Contains('同时使用 `$change-governance`')) "codex-qq-hook troubleshooting does not route unknown causes through change-governance"
Assert-True ($globalContent.Contains("把用户表达视为共同理解目标的权威输入而非必然完整的目标")) "Global kernel is missing collaborative requirement insight"
Assert-True ($globalContent.Contains("质量同等充分时再以较低上下文与 Token 成本为优，前两者均不变差时再提升速度")) "Global kernel is missing the quality-token-speed priority"
$deliverySkillContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\delivery-workflow\SKILL.md") -Raw -Encoding UTF8
Assert-True ($deliverySkillContent.Contains("把初始请求作为共同理解问题的起点")) "delivery-workflow is missing collaborative requirement discovery"
Assert-True ($deliverySkillContent.Contains("整体结果未以局部正确偏离目标")) "delivery-workflow is missing final requirement-alignment review"
Assert-True ($deliverySkillContent.Contains("优先沿当前目标链形成最近的可验证交付闭环")) "delivery-workflow is missing vertical validation closure feedback"

$allowedBehaviorTags = @(Get-StringArray $contract.allowed_behavior_tags)
Assert-True (($allowedBehaviorTags | Sort-Object -Unique).Count -eq $allowedBehaviorTags.Count) "Trigger contract contains duplicate allowed behavior tags"
$behaviorTagDefinitions = $contract.behavior_tag_definitions
Assert-True ($null -ne $behaviorTagDefinitions) "Trigger contract has no behavior tag definitions"
$definedBehaviorTags = @($behaviorTagDefinitions.PSObject.Properties.Name)
Assert-True ((($definedBehaviorTags | Sort-Object) -join "`n") -ceq (($allowedBehaviorTags | Sort-Object) -join "`n")) "Behavior tag definitions do not exactly match allowed behavior tags"
foreach ($tag in $allowedBehaviorTags) {
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$behaviorTagDefinitions.$tag)) "Behavior tag is missing its definition: $tag"
}
$peerSkills = @($contract.peer_skills)
$peerSkillNames = @($peerSkills | ForEach-Object { [string]$_.name })
Assert-True ($peerSkillNames.Count -gt 0) "Trigger contract has no peer-skill coexistence catalog"
Assert-True (($peerSkillNames | Sort-Object -Unique).Count -eq $peerSkillNames.Count) "Trigger contract contains duplicate peer skill names"
foreach ($peerSkill in $peerSkills) {
    Assert-True ([string]$peerSkill.name -match '^peer-[a-z0-9][a-z0-9-]*$') "Invalid peer skill name: $($peerSkill.name)"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$peerSkill.description)) "Peer skill is missing its description: $($peerSkill.name)"
}
$strictRoutingCaseIds = @(Get-StringArray $contract.strict_routing_case_ids)
Assert-True (($strictRoutingCaseIds | Sort-Object -Unique).Count -eq $strictRoutingCaseIds.Count) "Trigger contract contains duplicate strict routing case ids"
$strictReferenceCaseIds = @(Get-StringArray $contract.strict_reference_case_ids)
Assert-True (($strictReferenceCaseIds | Sort-Object -Unique).Count -eq $strictReferenceCaseIds.Count) "Trigger contract contains duplicate strict reference case ids"

$requiredCases = @(
    "mechanical-document-edit"
    "collaborative-requirement-insight"
    "quality-token-speed-priority"
    "architecture-discovery-before-implementation"
    "implicit-architecture-integration"
    "shared-responsibility-discovery-and-adoption"
    "authority-change-impact-closure"
    "surface-similarity-no-shared-owner"
    "one-off-generated-artifact"
    "cpp-include-edit"
    "ast-structural-call-search"
    "ast-no-match-needs-source-evidence"
    "literal-text-search"
    "bounded-file-discovery"
    "powershell-command-authoring"
    "semantic-safe-rename"
    "event-log-context-recovery"
    "qq-hook-explicit-enable"
    "qq-hook-status-read-only"
    "qq-direct-message-required"
    "qq-hook-troubleshooting"
    "cross-turn-dependent-plan"
    "full-delivery-chain"
    "delivery-requirements-contract"
    "delivery-planning-contract"
    "delivery-task-contract"
    "delivery-feedback-contract"
    "vertical-validation-closure-selection"
    "protected-baseline-change-discovered"
    "workflow-cli-gate-boundary"
    "single-task-cli-formatting"
    "active-goal-reasoning-shift"
    "explicit-thread-reasoning-setting"
    "reasoning-depth-discussion-only"
    "coordinate-frame-conversion"
    "transform-formula-convention"
    "bug-root-cause-fix"
    "formal-entry-migration"
    "project-metadata-refresh"
    "shared-blocking-gate"
    "fact-conflict-read-only"
    "long-term-without-scope-expansion"
    "review-only-no-alternative-execution"
    "ast-rewrite-preview"
    "event-log-explicit-history-request"
    "fd-full-path-directory-discovery"
    "powershell-readonly-command-inspection"
    "mixed-cpp-powershell-review"
    "long-context-latest-simple-request"
    "ui-spatial-layout-with-peer"
    "ui-copy-review-with-peer"
    "ue-transform-with-peer"
    "ue-mechanical-field-with-peer"
    "qq-troubleshooting-with-powershell"
)

$seenCases = @{}
$positiveCoverage = @{}
$negativeCoverage = @{}
foreach ($skill in $requiredSkills) {
    $positiveCoverage[$skill] = 0
    $negativeCoverage[$skill] = 0
}

foreach ($case in @($contract.cases)) {
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$case.id)) "Trigger contract contains a case without an id"
    Assert-True ([string]$case.id -match '^[a-z0-9][a-z0-9-]*$') "Invalid trigger case id: $($case.id)"
    Assert-True (-not $seenCases.ContainsKey([string]$case.id)) "Duplicate trigger case id: $($case.id)"
    $seenCases[[string]$case.id] = $true
    Assert-True (@("positive", "negative", "boundary", "behavior") -contains [string]$case.kind) "Invalid kind for trigger case $($case.id): $($case.kind)"
    Assert-True (-not [string]::IsNullOrWhiteSpace([string]$case.request)) "Trigger case $($case.id) has an empty request"

    $expectedSkills = @(Get-StringArray $case.expected_skills)
    $forbiddenSkills = @(Get-StringArray $case.forbidden_skills)
    $availablePeerSkills = @(Get-StringArray $case.available_peer_skills)
    $expectedPeerSkills = @(Get-StringArray $case.expected_peer_skills)
    $forbiddenPeerSkills = @(Get-StringArray $case.forbidden_peer_skills)
    $expectedBehaviors = @(Get-StringArray $case.expected_behavior_tags)
    $forbiddenBehaviors = @(Get-StringArray $case.forbidden_behavior_tags)

    Assert-Disjoint $expectedSkills $forbiddenSkills "Case $($case.id) skill contract"
    Assert-Disjoint $expectedPeerSkills $forbiddenPeerSkills "Case $($case.id) peer-skill contract"
    Assert-Disjoint $expectedBehaviors $forbiddenBehaviors "Case $($case.id) behavior contract"

    foreach ($skill in @($expectedSkills + $forbiddenSkills)) {
        Assert-True ($requiredSkills -contains $skill) "Case $($case.id) references undeclared skill: $skill"
    }
    foreach ($skill in $expectedSkills) {
        $positiveCoverage[$skill]++
    }
    foreach ($skill in $forbiddenSkills) {
        $negativeCoverage[$skill]++
    }

    foreach ($peerSkill in @($availablePeerSkills + $expectedPeerSkills + $forbiddenPeerSkills)) {
        Assert-True ($peerSkillNames -contains $peerSkill) "Case $($case.id) references undeclared peer skill: $peerSkill"
    }
    foreach ($peerSkill in @($expectedPeerSkills + $forbiddenPeerSkills)) {
        Assert-True ($availablePeerSkills -contains $peerSkill) "Case $($case.id) constrains unavailable peer skill: $peerSkill"
    }

    foreach ($referenceSkill in $referenceEvaluationSkills) {
        $expectedProperty = "expected_$($referenceSkill.Replace('-', '_'))_references"
        $references = @(Get-StringArray $case.$expectedProperty)
        if ($references.Count -gt 0) {
            Assert-True ($expectedSkills -contains $referenceSkill) "Case $($case.id) expects $referenceSkill references without the skill"
        }
        foreach ($reference in $references) {
            $referencePath = Join-Path (Join-Path (Join-Path $ProjectRoot "skills") $referenceSkill) ("references\" + $reference)
            Assert-True (Test-Path -LiteralPath $referencePath -PathType Leaf) "Case $($case.id) references missing $referenceSkill file: $reference"
        }
    }

    foreach ($tag in @($expectedBehaviors + $forbiddenBehaviors)) {
        Assert-True ($allowedBehaviorTags -contains $tag) "Case $($case.id) uses undeclared behavior tag: $tag"
    }
}

foreach ($requiredCase in $requiredCases) {
    Assert-True ($seenCases.ContainsKey($requiredCase)) "Missing required trigger case: $requiredCase"
}
foreach ($strictRoutingCaseId in $strictRoutingCaseIds) {
    Assert-True ($seenCases.ContainsKey($strictRoutingCaseId)) "Strict routing policy references missing case: $strictRoutingCaseId"
}
foreach ($strictReferenceCaseId in $strictReferenceCaseIds) {
    Assert-True ($seenCases.ContainsKey($strictReferenceCaseId)) "Strict reference policy references missing case: $strictReferenceCaseId"
    $strictReferenceCase = @($contract.cases | Where-Object { [string]$_.id -eq $strictReferenceCaseId })[0]
    Assert-True (@($strictReferenceCase.expected_skills | ForEach-Object { [string]$_ } | Where-Object { $referenceEvaluationSkills -contains $_ }).Count -gt 0) "Strict reference case selects no conditional-reference skill: $strictReferenceCaseId"
}

foreach ($skill in $requiredSkills) {
    Assert-True ($positiveCoverage[$skill] -gt 0) "Required skill has no positive route case: $skill"
    Assert-True ($negativeCoverage[$skill] -gt 0) "Required skill has no non-trigger case: $skill"
}

Write-Output "Routing contract valid: $($seenCases.Count) cases; $($strictRoutingCaseIds.Count) strict routing and $($strictReferenceCaseIds.Count) strict reference cases; $($requiredSkills.Count)/$($requiredSkills.Count) skills have positive and non-trigger coverage; global, metadata, references, peer skills, and policy tags resolve."
