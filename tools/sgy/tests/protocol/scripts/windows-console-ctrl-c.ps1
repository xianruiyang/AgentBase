param(
    [Parameter(Mandatory = $true)][string]$Driver,
    [Parameter(Mandatory = $true)][string]$Engine,
    [Parameter(Mandatory = $true)][string]$Source
)

$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class ConsoleCtrlCProbe {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct STARTUPINFO {
        public int cb;
        public string lpReserved;
        public string lpDesktop;
        public string lpTitle;
        public int dwX;
        public int dwY;
        public int dwXSize;
        public int dwYSize;
        public int dwXCountChars;
        public int dwYCountChars;
        public int dwFillAttribute;
        public int dwFlags;
        public short wShowWindow;
        public short cbReserved2;
        public IntPtr lpReserved2;
        public IntPtr hStdInput;
        public IntPtr hStdOutput;
        public IntPtr hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct PROCESS_INFORMATION {
        public IntPtr hProcess;
        public IntPtr hThread;
        public uint dwProcessId;
        public uint dwThreadId;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool CreateProcessW(
        string applicationName, StringBuilder commandLine, IntPtr processAttributes,
        IntPtr threadAttributes, bool inheritHandles, uint creationFlags, IntPtr environment,
        string currentDirectory, ref STARTUPINFO startupInfo, out PROCESS_INFORMATION processInfo);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool FreeConsole();
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool AttachConsole(uint processId);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool SetConsoleCtrlHandler(IntPtr handler, bool add);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool GenerateConsoleCtrlEvent(uint ctrlEvent, uint processGroupId);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool GetExitCodeProcess(IntPtr process, out uint exitCode);
    [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr handle);
}
'@

function Quote-ProcessArgument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

$arguments = @(
    (Quote-ProcessArgument $Driver),
    'exec', '--engine', (Quote-ProcessArgument $Engine), '--cache', 'off', '--',
    'run', '-p', (Quote-ProcessArgument 'console.log($A)'), '-r',
    (Quote-ProcessArgument 'logger.info($A)'), '-i', '-l', 'ts',
    (Quote-ProcessArgument $Source)
) -join ' '

$startup = [ConsoleCtrlCProbe+STARTUPINFO]::new()
$startup.cb = [Runtime.InteropServices.Marshal]::SizeOf($startup)
$startup.dwFlags = 1 # STARTF_USESHOWWINDOW
$startup.wShowWindow = 6 # SW_MINIMIZE
$process = [ConsoleCtrlCProbe+PROCESS_INFORMATION]::new()
$flags = 0x10 -bor 0x200 # CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP
if (-not [ConsoleCtrlCProbe]::CreateProcessW(
    $Driver, [Text.StringBuilder]::new($arguments), [IntPtr]::Zero, [IntPtr]::Zero,
    $false, $flags, [IntPtr]::Zero, (Split-Path -Parent $Source), [ref]$startup, [ref]$process
)) {
    throw "CreateProcessW failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
}

try {
    Start-Sleep -Milliseconds 1200
    [void][ConsoleCtrlCProbe]::FreeConsole()
    if (-not [ConsoleCtrlCProbe]::AttachConsole($process.dwProcessId)) {
        throw "AttachConsole failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
    }
    [void][ConsoleCtrlCProbe]::SetConsoleCtrlHandler([IntPtr]::Zero, $true)
    if (-not [ConsoleCtrlCProbe]::GenerateConsoleCtrlEvent(0, $process.dwProcessId)) {
        throw "GenerateConsoleCtrlEvent failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
    }
    if ([ConsoleCtrlCProbe]::WaitForSingleObject($process.hProcess, 10000) -ne 0) {
        throw 'sgy did not exit within 10 seconds after Ctrl+C'
    }
    $exitCode = [uint32]0
    if (-not [ConsoleCtrlCProbe]::GetExitCodeProcess($process.hProcess, [ref]$exitCode)) {
        throw "GetExitCodeProcess failed: $([Runtime.InteropServices.Marshal]::GetLastWin32Error())"
    }
    if ($exitCode -ne 130) {
        throw "expected wrapper exit 130, got $exitCode"
    }
}
finally {
    [void][ConsoleCtrlCProbe]::CloseHandle($process.hThread)
    [void][ConsoleCtrlCProbe]::CloseHandle($process.hProcess)
}
