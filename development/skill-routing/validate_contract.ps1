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

$contractPath = Join-Path $PSScriptRoot "trigger-cases.json"
$contract = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ($contract.schema_version -eq 2) "Unsupported trigger contract schema: $($contract.schema_version)"

$requiredSkills = @(Get-StringArray $contract.required_skills)
Assert-True ($requiredSkills.Count -gt 0) "Trigger contract has no required skills"
Assert-True (($requiredSkills | Sort-Object -Unique).Count -eq $requiredSkills.Count) "Trigger contract contains duplicate required skills"

$globalPath = Join-Path $ProjectRoot "global\AGENTS.md"
$globalItem = Get-Item -LiteralPath $globalPath
$globalContent = Get-Content -LiteralPath $globalPath -Raw -Encoding UTF8
Assert-True ($globalItem.Length -le [int]$contract.global_max_bytes) "Global AGENTS.md is $($globalItem.Length) bytes; contract limit is $($contract.global_max_bytes)"
$projectAgentsPath = Join-Path $ProjectRoot "AGENTS.md"
$projectAgentsItem = Get-Item -LiteralPath $projectAgentsPath
$projectAgentsContent = Get-Content -LiteralPath $projectAgentsPath -Raw -Encoding UTF8
$combinedInstructionBytes = $globalItem.Length + $projectAgentsItem.Length
Assert-True ($combinedInstructionBytes -le 28672) "AgentBase global and project AGENTS.md files use $combinedInstructionBytes bytes; keep at least 4 KiB below Codex's default 32 KiB project instruction limit"
Assert-True ($projectAgentsContent.Contains("本仓库文件本身不创建 Git 外部写授权")) "Project AGENTS.md must not treat repository text as self-granted Git external-write authorization"

$requiredGlobalFragments = @(
    '`must` 表示必须执行'
    '`should` 表示默认执行'
    '`must not` 表示不得执行'
    '对象与范围更具体且不反转上位目标'
    '用户对期望结果、偏好、优先级和授权范围的明确表达用于确定目标'
    '规范来源用于确定目标契约，有效证据用于判断系统现状、原因、约束和实现结果'
    '不得静默改写用户目标'
    '不得为迎合而接受错误前提或弱化结论'
    '不创建替代目标或实施授权'
    '长期净收益和整个系统总成本'
    '不默认把实现限定为最窄局部补丁'
    '为使用户要求的行为成立并接入唯一正式入口而不可缺少'
    '仅改善整体架构但不影响本次结果的调整需要另行授权'
    '长期收益不得作为扩大范围或替代用户裁决的理由'
    '不得仅凭自身声明创建外部写入、发布、凭据使用或高风险操作授权'
    '多个入口或第二状态源的方案裁决'
    '临时路径风险与退出条件'
    '需要根据素材、专业判断或表达选择组织时'
    '默认属于长期资产'
    '不替代实施后的必要验收和完成证据'
    '属于启动例外'
    '模块测试验证模块契约'
    '原场景、同类变体和相近非触发场景'
    '长期资产的验证还应确认本次改动已接入正确职责和唯一正式入口'
    '在 active goal 中把深度作为 next-turn 可调配置'
    '简单且已限制的命令输出不创建日志文件'
    '新一轮调试前只清理会干扰当前判断且目标范围明确的旧日志'
    '工作流程的目标、阶段、状态、依赖、完成和例外由适用文档定义'
    'CLI、脚本、索引、缓存和生成视图只辅助编辑、查询、压缩与机械校验'
    '防止本次操作写错对象、破坏数据、并发覆盖、资源无界或混用查询快照'
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
    "ast-grep-token-safe" = "不用于单纯字符串"
    "change-governance" = "不用于规格已完整"
    "codex-event-logger" = "当前上下文充分"
    "codex-qq-hook" = "状态查询不得创建或改写配置"
    "delivery-workflow" = "不用于规格已完整的单轮实现"
    "powershell-usage" = "不用于没有 PowerShell 命令"
    "reasoning-governor" = "没有 active Goal 时不用于模型自主切换"
    "symbol-structure-workflow" = "普通字符串"
    "task-table-manager" = "不用于单轮修改"
    "understand-space" = "不因正文偶然出现空间词触发"
}

foreach ($skill in $requiredSkills) {
    $skillRoot = Join-Path (Join-Path $ProjectRoot "skills") $skill
    $skillPath = Join-Path $skillRoot "SKILL.md"
    $metadataPath = Join-Path $skillRoot "agents\openai.yaml"
    Assert-True (Test-Path -LiteralPath $skillPath -PathType Leaf) "Missing SKILL.md for required skill: $skill"
    Assert-True (Test-Path -LiteralPath $metadataPath -PathType Leaf) "Missing agents/openai.yaml for required skill: $skill"

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

foreach ($behaviorScriptName in @("build_behavior_inputs.ps1", "validate_behavior_results.ps1")) {
    $behaviorScriptContent = Get-Content -LiteralPath (Join-Path $PSScriptRoot $behaviorScriptName) -Raw -Encoding UTF8
    Assert-True (-not ($behaviorScriptContent -match 'Get-ChildItem[^\r\n]+-Recurse')) "$behaviorScriptName must not hash recursive skill artifacts"
    Assert-True ($behaviorScriptContent.Contains('"SKILL.md"')) "$behaviorScriptName must hash each evaluated SKILL.md"
    Assert-True ($behaviorScriptContent.Contains('"agents\openai.yaml"')) "$behaviorScriptName must hash each evaluated agents/openai.yaml"
}

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
Assert-True ($taskTableScriptContent.Contains('command_completion_context')) "taskctl is missing its bounded final-review context"
Assert-True ($taskTableScriptContent.Contains('needs_review_count')) "taskctl status does not expose the review count"
Assert-True ($taskTableScriptContent.Contains('upstream_index_derived_content_mismatch')) "taskctl does not bind cached index content to current workflow documents"
Assert-True ($taskTableScriptContent.Contains('completion snapshot changed')) "taskctl completion pagination is missing snapshot consistency"
Assert-True ($taskTableScriptContent.Contains('TASK-PAGINATION-SNAPSHOT')) "taskctl completion snapshot gate is not structured"
Assert-True ($taskTableScriptContent.Contains('owner_mismatch')) "taskctl does not report owner conflicts as diagnostics"
Assert-True ($taskTableScriptContent.Contains('dependency_cycle')) "taskctl does not report dependency cycles as diagnostics"
Assert-True ($taskTableScriptContent.Contains('source_snapshot')) "taskctl results do not bind evidence to upstream source snapshots"
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
Assert-True ($deliverySkillContent.Contains('requirements.md') -and $deliverySkillContent.Contains('user-design.md')) "delivery-workflow does not separate protected user sources"
Assert-True ($deliverySkillContent.Contains('模型设计、分析、方案、任务状态、快照、索引、结构检查和各阶段审核都只是中间结果')) "delivery-workflow does not limit intermediate reviews"
Assert-True ($deliverySkillContent.Contains('Markdown 阶段文档是语义真源')) "delivery-workflow does not keep documents authoritative"
Assert-True ($deliveryScriptContent.Contains('delivery.protected-baseline')) "workctl is missing protected baseline support"
Assert-True ($deliveryScriptContent.Contains('baseline_source_drift')) "workctl does not report protected-source drift as a diagnostic"
Assert-True ($deliveryScriptContent.Contains('exclusive_write_json')) "workctl protected baseline is not created exclusively"
Assert-True ($deliveryScriptContent.Contains('baseline_has_no_final_target')) "workctl does not diagnose a snapshot without final targets"
Assert-True ($deliveryScriptContent.Contains('WORK-SNAPSHOT-RACE')) "workctl snapshot-race gate is not structured"
Assert-True ($deliveryScriptContent.Contains('history')) "workctl does not preserve prior confirmation snapshots for new cycles"
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

$eventLoggerRoot = Join-Path $ProjectRoot "skills\codex-event-logger"
$eventLoggerSkillContent = Get-Content -LiteralPath (Join-Path $eventLoggerRoot "SKILL.md") -Raw -Encoding UTF8
$eventLoggerReaderPath = Join-Path $eventLoggerRoot "scripts\read_codex_turn_log.py"
Assert-True (-not (Test-Path -LiteralPath (Join-Path $eventLoggerRoot "HOOK_INSTALL.md"))) "codex-event-logger keeps installation documentation inside the skill root"
Assert-True (Test-Path -LiteralPath $eventLoggerReaderPath -PathType Leaf) "codex-event-logger is missing its bounded reader"
Assert-True ($eventLoggerSkillContent.Contains('read_codex_turn_log.py')) "codex-event-logger SKILL.md does not route reads through the bounded reader"
Assert-True (-not $eventLoggerSkillContent.Contains('Get-Content -Raw')) "codex-event-logger SKILL.md contains an unbounded raw read"
Assert-True (Test-Path -LiteralPath (Join-Path $eventLoggerRoot "tests\test_event_logger.py") -PathType Leaf) "codex-event-logger is missing its regression tests"

$sgyScriptsRoot = Join-Path $ProjectRoot "skills\ast-grep-token-safe\scripts"
$sgyRuntimeManifestPath = Join-Path $sgyScriptsRoot "runtime-manifest.yml"
$sgyReleaseRecordPath = Join-Path $sgyScriptsRoot "provenance\release-record.json"
$sgyRuntimeManifest = Get-Content -LiteralPath $sgyRuntimeManifestPath -Raw -Encoding UTF8
$sgyReleaseRecord = Get-Content -LiteralPath $sgyReleaseRecordPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ($sgyReleaseRecord.schema -eq "sgy.skill-runtime-release/v1") "sgy release record has an unsupported schema"
Assert-True ($sgyReleaseRecord.version -eq "0.1.0") "sgy release record version does not match the skill runtime"
Assert-True ($sgyReleaseRecord.pathBase -eq "scripts") "sgy release record paths must be relative to the skill scripts directory"
Assert-True ($sgyReleaseRecord.source.revision -match '^sha256:[0-9a-f]{64}$') "sgy release record has an invalid source revision"
Assert-True ($sgyRuntimeManifest.Contains("source_revision: $($sgyReleaseRecord.source.revision)")) "sgy runtime manifest does not identify its source revision"
Assert-True ($sgyRuntimeManifest.Contains("release_record: provenance/release-record.json")) "sgy runtime manifest does not link its release record"

$sgySnapshotPath = Join-Path $sgyScriptsRoot ([string]$sgyReleaseRecord.source.snapshot)
$sgySnapshot = Get-Content -LiteralPath $sgySnapshotPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-True ($sgySnapshot.schema -eq "sgy.source-snapshot/v1") "sgy source snapshot has an unsupported schema"
Assert-True ($sgySnapshot.sourceRevision -eq $sgyReleaseRecord.source.revision) "sgy source snapshot revision does not match the release record"
Assert-True ([int]$sgySnapshot.fileCount -eq [int]$sgyReleaseRecord.source.fileCount) "sgy source snapshot file count does not match the release record"

$sgyCargoLockPath = Join-Path $ProjectRoot ([string]$sgyReleaseRecord.rustsec.projectLockfile)
$sgyCargoLockHash = (Get-FileHash -LiteralPath $sgyCargoLockPath -Algorithm SHA256).Hash.ToLowerInvariant()
Assert-True ($sgyCargoLockHash -eq [string]$sgyReleaseRecord.source.cargoLockSha256) "sgy Cargo.lock does not match the signed release source"
Assert-True ($sgyReleaseRecord.rustsec.status -eq "passed") "sgy RustSec audit is not signed as passed"
Assert-True ($sgyReleaseRecord.rustsec.cargoAuditArchiveSha256 -match '^[0-9a-f]{64}$') "sgy RustSec tool archive hash is invalid"
Assert-True ($sgyReleaseRecord.rustsec.advisoryDbRevision -match '^[0-9a-f]{40}$') "sgy RustSec advisory database revision is invalid"
Assert-True ([int]$sgyReleaseRecord.rustsec.advisoryCount -gt 0) "sgy RustSec audit did not record a non-empty advisory database"
Assert-True ([int]$sgyReleaseRecord.rustsec.dependencyCount -gt 0) "sgy RustSec audit did not record scanned dependencies"

$sgyTargets = @($sgyReleaseRecord.targets)
Assert-True ($sgyTargets.Count -eq 2) "sgy release record must contain exactly the two supported native targets"
$sgyScriptsPrefix = [IO.Path]::GetFullPath($sgyScriptsRoot).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
foreach ($sgyTarget in $sgyTargets) {
    Assert-True ($sgyTarget.nativeBuild.status -eq "passed") "sgy target is missing passed native build evidence: $($sgyTarget.target)"
    Assert-True ($sgyTarget.archiveSha256 -match '^[0-9a-f]{64}$') "sgy target has an invalid archive hash: $($sgyTarget.target)"

    $sgyBinaryPath = [IO.Path]::GetFullPath((Join-Path $sgyScriptsRoot ([string]$sgyTarget.binary.path)))
    $sgyManifestPath = [IO.Path]::GetFullPath((Join-Path $sgyScriptsRoot ([string]$sgyTarget.manifest)))
    Assert-True ($sgyBinaryPath.StartsWith($sgyScriptsPrefix, [StringComparison]::OrdinalIgnoreCase)) "sgy binary path escapes the skill scripts directory: $($sgyTarget.binary.path)"
    Assert-True ($sgyManifestPath.StartsWith($sgyScriptsPrefix, [StringComparison]::OrdinalIgnoreCase)) "sgy provenance path escapes the skill scripts directory: $($sgyTarget.manifest)"
    Assert-True (Test-Path -LiteralPath $sgyBinaryPath -PathType Leaf) "sgy release binary is missing: $($sgyTarget.binary.path)"
    Assert-True (Test-Path -LiteralPath $sgyManifestPath -PathType Leaf) "sgy target provenance manifest is missing: $($sgyTarget.manifest)"

    $sgyBinaryItem = Get-Item -LiteralPath $sgyBinaryPath
    $sgyBinaryHash = (Get-FileHash -LiteralPath $sgyBinaryPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Assert-True ([UInt64]$sgyBinaryItem.Length -eq [UInt64]$sgyTarget.binary.bytes) "sgy binary size does not match its release record: $($sgyTarget.target)"
    Assert-True ($sgyBinaryHash -eq [string]$sgyTarget.binary.sha256) "sgy binary hash does not match its release record: $($sgyTarget.target)"
    Assert-True ($sgyRuntimeManifest.Contains("sha256: $sgyBinaryHash")) "sgy runtime manifest does not contain the installed binary hash: $($sgyTarget.target)"
    Assert-True ($sgyRuntimeManifest.Contains("archive_sha256: $($sgyTarget.archiveSha256)")) "sgy runtime manifest does not contain the archive hash: $($sgyTarget.target)"

    $sgyTargetManifest = Get-Content -LiteralPath $sgyManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-True ($sgyTargetManifest.schema -eq "sgy.release/v1") "sgy target provenance manifest has an unsupported schema: $($sgyTarget.target)"
    Assert-True ($sgyTargetManifest.target -eq $sgyTarget.target) "sgy target provenance identifies a different target: $($sgyTarget.target)"
    Assert-True ($sgyTargetManifest.archive -eq $sgyTarget.archive) "sgy target archive name does not match its provenance: $($sgyTarget.target)"
    Assert-True ($sgyTargetManifest.source.revision -eq $sgyReleaseRecord.source.revision) "sgy target provenance source does not match the release record: $($sgyTarget.target)"
    Assert-True ($sgyTargetManifest.source.cargoLockSha256 -eq $sgyReleaseRecord.source.cargoLockSha256) "sgy target provenance Cargo.lock does not match the release record: $($sgyTarget.target)"
    $sgyManifestBinary = @($sgyTargetManifest.files | Where-Object { $_.path -eq [IO.Path]::GetFileName($sgyBinaryPath) })
    Assert-True ($sgyManifestBinary.Count -eq 1) "sgy target provenance does not contain exactly one runtime binary: $($sgyTarget.target)"
    Assert-True ($sgyManifestBinary[0].sha256 -eq $sgyBinaryHash) "sgy target provenance binary hash does not match the installed runtime: $($sgyTarget.target)"
    Assert-True ([UInt64]$sgyManifestBinary[0].bytes -eq [UInt64]$sgyBinaryItem.Length) "sgy target provenance binary size does not match the installed runtime: $($sgyTarget.target)"
}

$powerShellSkillContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\powershell-usage\SKILL.md") -Raw -Encoding UTF8
Assert-True ($powerShellSkillContent.Contains('--heading -M 240 --max-columns-preview')) "powershell-usage rg example is missing bounded file identity and width options"
Assert-True ($powerShellSkillContent.Contains('Select-Object -First 80')) "powershell-usage rg example is missing its total line limit"
Assert-True ($powerShellSkillContent.Contains('PowerShell 7（`pwsh`）')) "powershell-usage does not declare its PowerShell 7 baseline"
Assert-True ($powerShellSkillContent.Contains('项目环境初始化入口一次性完成')) "powershell-usage does not delegate host verification to environment initialization"
Assert-True (-not $powerShellSkillContent.Contains('$PSVersionTable.PSVersion')) "powershell-usage performs redundant per-command host version detection"
Assert-True (-not $powerShellSkillContent.Contains('Windows PowerShell 5.1')) "powershell-usage keeps obsolete Windows PowerShell 5.1 guidance"

$symbolMetadataPath = Join-Path $ProjectRoot "skills\symbol-structure-workflow\agents\openai.yaml"
$symbolMetadata = Get-Content -LiteralPath $symbolMetadataPath -Raw -Encoding UTF8
Assert-True ($symbolMetadata -match '(?m)^\s{4}- type:\s*"mcp"\s*$') "symbol-structure-workflow must declare an MCP tool dependency"
Assert-True ($symbolMetadata -match '(?m)^\s{6}value:\s*"vscode-lsp-mcp"\s*$') "symbol-structure-workflow MCP dependency must target vscode-lsp-mcp"

$spaceSkillContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\understand-space\SKILL.md") -Raw -Encoding UTF8
Assert-True ($spaceSkillContent.Contains("齐次坐标列向量、变换左乘")) "understand-space must declare the convention used by its transform formulas"
Assert-True ($spaceSkillContent.Contains("不能直接套用本文公式")) "understand-space must require API-specific convention mapping"

$qqResolverPath = Join-Path $ProjectRoot "skills\codex-qq-hook\scripts\resolve_codex_home.ps1"
$qqStopScriptContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\codex-qq-hook\scripts\codex_stop_qq_notify.ps1") -Raw -Encoding UTF8
$qqInstallerContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\codex-qq-hook\scripts\install_global_qq_hook.ps1") -Raw -Encoding UTF8
Assert-True (Test-Path -LiteralPath $qqResolverPath -PathType Leaf) "codex-qq-hook is missing its location-independent Codex root resolver"
Assert-True ($qqStopScriptContent.Contains("Resolve-AgentBaseCodexHome")) "codex-qq-hook Stop handler still derives Codex root from its installation path"
Assert-True ($qqInstallerContent.Contains('[string]$CodexRoot')) "codex-qq-hook installer must accept an explicit Codex root"

$allMarkdownFiles = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot "skills") -Recurse -File -Filter "*.md"
foreach ($markdownFile in $allMarkdownFiles) {
    $markdown = Get-Content -LiteralPath $markdownFile.FullName -Raw -Encoding UTF8
    foreach ($linkMatch in [regex]::Matches($markdown, '\[[^\]]+\]\((?<target>[^)]+)\)')) {
        $target = $linkMatch.Groups["target"].Value.Trim()
        if ($target.StartsWith("#") -or $target -match '^[a-zA-Z][a-zA-Z0-9+.-]*:') {
            continue
        }
        $targetPath = ($target -split '#', 2)[0].Trim('<', '>')
        if ([string]::IsNullOrWhiteSpace($targetPath)) {
            continue
        }
        $resolvedTarget = Join-Path $markdownFile.DirectoryName ([Uri]::UnescapeDataString($targetPath))
        Assert-True (Test-Path -LiteralPath $resolvedTarget) "Broken relative Markdown link in $($markdownFile.FullName): $target"
    }
}

$workflowPath = Join-Path $ProjectRoot ".github\workflows\validate.yml"
$workflowContent = Get-Content -LiteralPath $workflowPath -Raw -Encoding UTF8
Assert-True ($workflowContent.Contains("npm run verify:release")) "Repository CI does not run the vscode-lsp-mcp release gate"
Assert-True ($workflowContent.Contains("rustsec/audit-check@")) "Repository CI does not run the RustSec gate"
Assert-True ($workflowContent.Contains("sgy-windows:")) "Repository CI is missing the Windows sgy native gate"
Assert-True ($workflowContent.Contains("validate_behavior_results.ps1") -and $workflowContent.Contains("evidence\current.json")) "Repository CI does not validate current blind behavior evidence"
Assert-True ($workflowContent.Contains("test_behavior_fingerprint.ps1")) "Repository CI does not verify line-ending-neutral behavior fingerprints"
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
$changeSkillContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\change-governance\SKILL.md") -Raw -Encoding UTF8
Assert-True ($changeSkillContent.Contains("多个入口或第二状态源的方案裁决")) "change-governance does not expose its multi-entry decision trigger"
Assert-True ($changeSkillContent.Contains("临时路径风险评审")) "change-governance does not expose its temporary-path review trigger"
$qqSkillContent = Get-Content -LiteralPath (Join-Path $ProjectRoot "skills\codex-qq-hook\SKILL.md") -Raw -Encoding UTF8
Assert-True ($qqSkillContent.Contains('同时使用 `$change-governance`')) "codex-qq-hook troubleshooting does not route unknown causes through change-governance"

$allowedBehaviorTags = @(Get-StringArray $contract.allowed_behavior_tags)
Assert-True (($allowedBehaviorTags | Sort-Object -Unique).Count -eq $allowedBehaviorTags.Count) "Trigger contract contains duplicate allowed behavior tags"

$requiredCases = @(
    "mechanical-document-edit"
    "architecture-discovery-before-implementation"
    "implicit-architecture-integration"
    "one-off-generated-artifact"
    "cpp-include-edit"
    "ast-structural-call-search"
    "literal-text-search"
    "bounded-file-discovery"
    "powershell-command-authoring"
    "semantic-safe-rename"
    "event-log-context-recovery"
    "qq-hook-explicit-enable"
    "qq-hook-status-read-only"
    "qq-hook-troubleshooting"
    "cross-turn-dependent-plan"
    "full-delivery-chain"
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
    $references = @(Get-StringArray $case.expected_change_governance_references)
    $expectedBehaviors = @(Get-StringArray $case.expected_behavior_tags)
    $forbiddenBehaviors = @(Get-StringArray $case.forbidden_behavior_tags)

    Assert-Disjoint $expectedSkills $forbiddenSkills "Case $($case.id) skill contract"
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

    if ($references.Count -gt 0) {
        Assert-True ($expectedSkills -contains "change-governance") "Case $($case.id) expects change-governance references without the skill"
    }
    foreach ($reference in $references) {
        $referencePath = Join-Path (Join-Path $ProjectRoot "skills\change-governance\references") $reference
        Assert-True (Test-Path -LiteralPath $referencePath -PathType Leaf) "Case $($case.id) references missing change-governance file: $reference"
    }

    foreach ($tag in @($expectedBehaviors + $forbiddenBehaviors)) {
        Assert-True ($allowedBehaviorTags -contains $tag) "Case $($case.id) uses undeclared behavior tag: $tag"
    }
}

foreach ($requiredCase in $requiredCases) {
    Assert-True ($seenCases.ContainsKey($requiredCase)) "Missing required trigger case: $requiredCase"
}

foreach ($skill in $requiredSkills) {
    Assert-True ($positiveCoverage[$skill] -gt 0) "Required skill has no positive route case: $skill"
    Assert-True ($negativeCoverage[$skill] -gt 0) "Required skill has no non-trigger case: $skill"
}

Write-Output "Routing contract valid: $($seenCases.Count) cases; $($requiredSkills.Count)/$($requiredSkills.Count) skills have positive and non-trigger coverage; global, metadata, references, and behavior tags resolve."
