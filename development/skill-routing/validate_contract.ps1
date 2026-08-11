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
$legacyNodePath = Join-Path $ProjectRoot "skills\task-table-manager\scripts\set-current-thread-reasoning-depth.mjs"
$legacyPowerShellPath = Join-Path $ProjectRoot "skills\task-table-manager\scripts\set-current-thread-reasoning-depth.ps1"
$legacyNodeContent = Get-Content -LiteralPath $legacyNodePath -Raw -Encoding UTF8
$legacyPowerShellContent = Get-Content -LiteralPath $legacyPowerShellPath -Raw -Encoding UTF8
Assert-True ($taskTableSkillContent.Contains('`$reasoning-governor`')) "task-table-manager must delegate reasoning depth to reasoning-governor"
Assert-True ($legacyNodeContent.Contains('../../reasoning-governor/scripts/reasoning-governor.mjs')) "Legacy Node reasoning entry must forward to reasoning-governor"
Assert-True ($legacyPowerShellContent.Contains('reasoning-governor\scripts\reasoning-governor.ps1')) "Legacy PowerShell reasoning entry must forward to reasoning-governor"

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

$lifecyclePath = Join-Path $ProjectRoot "skills\change-governance\references\lifecycle-and-entry.md"
$lifecycleContent = Get-Content -LiteralPath $lifecyclePath -Raw -Encoding UTF8
Assert-True ($lifecycleContent.Contains("优先更新已经承担相应规范职责的文档、配置或接口")) "Lifecycle reference is missing authority-carrier synchronization"

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
    "legacy-plan-assets-migration"
    "active-goal-reasoning-shift"
    "explicit-thread-reasoning-setting"
    "reasoning-depth-discussion-only"
    "coordinate-frame-conversion"
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
