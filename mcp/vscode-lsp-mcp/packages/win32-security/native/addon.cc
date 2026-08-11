#include <node_api.h>

#include <windows.h>
#include <aclapi.h>
#include <process.h>
#include <sddl.h>
#include <shlobj.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace {

struct ServerState {
  std::mutex mutex;
  std::wstring name;
  DWORD max_instances = 4;
  bool closed = false;
  HANDLE pending_first = INVALID_HANDLE_VALUE;
  std::set<HANDLE> handles;
};

struct ServerWrap {
  std::shared_ptr<ServerState> state;
};

struct ConnectionState {
  std::shared_ptr<ServerState> server;
  HANDLE handle = INVALID_HANDLE_VALUE;
  std::atomic<bool> closed{false};
  std::atomic<bool> read_pending{false};
  std::atomic<bool> write_pending{false};
};

struct ConnectionWrap {
  std::shared_ptr<ConnectionState> state;
};

struct SecurityInspection {
  bool protected_dacl = false;
  bool owner_current_user = false;
  bool current_user_full_control = false;
  bool system_full_control = false;
  bool other_users_denied = false;
};

const char* TargetArchitecture() {
#if defined(_M_X64) || defined(__x86_64__)
  return "x64";
#elif defined(_M_ARM64) || defined(__aarch64__)
  return "arm64";
#else
  return "unknown";
#endif
}

void ThrowLastError(napi_env env, const char* message) {
  napi_throw_error(env, nullptr, message);
}

bool SetString(napi_env env, napi_value object, const char* name, const char* value) {
  napi_value property;
  return napi_create_string_utf8(env, value, NAPI_AUTO_LENGTH, &property) == napi_ok &&
      napi_set_named_property(env, object, name, property) == napi_ok;
}

bool SetWideString(
    napi_env env,
    napi_value object,
    const char* name,
    const std::wstring& value) {
  napi_value property;
  return napi_create_string_utf16(
             env,
             reinterpret_cast<const char16_t*>(value.data()),
             value.size(),
             &property) == napi_ok &&
      napi_set_named_property(env, object, name, property) == napi_ok;
}

bool SetInteger(napi_env env, napi_value object, const char* name, int32_t value) {
  napi_value property;
  return napi_create_int32(env, value, &property) == napi_ok &&
      napi_set_named_property(env, object, name, property) == napi_ok;
}

bool SetBoolean(napi_env env, napi_value object, const char* name, bool value) {
  napi_value property;
  return napi_get_boolean(env, value, &property) == napi_ok &&
      napi_set_named_property(env, object, name, property) == napi_ok;
}

bool GetWideString(napi_env env, napi_value value, std::wstring* output) {
  size_t length = 0;
  if (napi_get_value_string_utf16(env, value, nullptr, 0, &length) != napi_ok) {
    return false;
  }
  std::vector<char16_t> buffer(length + 1);
  size_t copied = 0;
  if (napi_get_value_string_utf16(
          env,
          value,
          buffer.data(),
          buffer.size(),
          &copied) != napi_ok) {
    return false;
  }
  output->assign(
      reinterpret_cast<const wchar_t*>(buffer.data()),
      reinterpret_cast<const wchar_t*>(buffer.data()) + copied);
  return true;
}

std::vector<BYTE> CurrentUserSid() {
  HANDLE token = nullptr;
  if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token)) {
    return {};
  }
  DWORD size = 0;
  GetTokenInformation(token, TokenUser, nullptr, 0, &size);
  std::vector<BYTE> buffer(size);
  if (size == 0 || !GetTokenInformation(token, TokenUser, buffer.data(), size, &size)) {
    CloseHandle(token);
    return {};
  }
  CloseHandle(token);
  const auto* token_user = reinterpret_cast<const TOKEN_USER*>(buffer.data());
  const DWORD sid_length = GetLengthSid(token_user->User.Sid);
  std::vector<BYTE> sid(sid_length);
  if (!CopySid(sid_length, sid.data(), token_user->User.Sid)) {
    return {};
  }
  return sid;
}

std::vector<BYTE> SystemSid() {
  DWORD size = SECURITY_MAX_SID_SIZE;
  std::vector<BYTE> sid(size);
  if (!CreateWellKnownSid(WinLocalSystemSid, nullptr, sid.data(), &size)) {
    return {};
  }
  sid.resize(size);
  return sid;
}

std::wstring SidString(PSID sid) {
  LPWSTR raw = nullptr;
  if (!ConvertSidToStringSidW(sid, &raw)) {
    return {};
  }
  std::wstring value(raw);
  LocalFree(raw);
  return value;
}

PSECURITY_DESCRIPTOR CreateSecurityDescriptor(bool inheritable) {
  const auto current_sid = CurrentUserSid();
  if (current_sid.empty()) {
    return nullptr;
  }
  const std::wstring sid = SidString(const_cast<BYTE*>(current_sid.data()));
  if (sid.empty()) {
    return nullptr;
  }
  const std::wstring flags = inheritable ? L"OICI" : L"";
  const std::wstring sddl =
      L"O:" + sid + L"D:P(A;" + flags + L";GA;;;SY)(A;" + flags + L";GA;;;" + sid + L")";
  PSECURITY_DESCRIPTOR descriptor = nullptr;
  if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(
          sddl.c_str(),
          SDDL_REVISION_1,
          &descriptor,
          nullptr)) {
    return nullptr;
  }
  return descriptor;
}

SecurityInspection InspectSecurityDescriptor(
    PSECURITY_DESCRIPTOR descriptor,
    ACCESS_MASK required_access) {
  SecurityInspection result;
  if (descriptor == nullptr) {
    return result;
  }
  const auto current_sid = CurrentUserSid();
  const auto system_sid = SystemSid();
  if (current_sid.empty() || system_sid.empty()) {
    return result;
  }
  PSID owner = nullptr;
  BOOL owner_defaulted = FALSE;
  if (!GetSecurityDescriptorOwner(descriptor, &owner, &owner_defaulted) || owner == nullptr) {
    return result;
  }
  result.owner_current_user = EqualSid(owner, const_cast<BYTE*>(current_sid.data())) != FALSE;

  SECURITY_DESCRIPTOR_CONTROL control = 0;
  DWORD revision = 0;
  if (GetSecurityDescriptorControl(descriptor, &control, &revision)) {
    result.protected_dacl = (control & SE_DACL_PROTECTED) != 0;
  }

  PACL dacl = nullptr;
  BOOL present = FALSE;
  BOOL defaulted = FALSE;
  if (!GetSecurityDescriptorDacl(descriptor, &present, &dacl, &defaulted) ||
      !present || dacl == nullptr) {
    return result;
  }

  bool unexpected_ace = false;
  for (DWORD index = 0; index < dacl->AceCount; ++index) {
    void* raw_ace = nullptr;
    if (!GetAce(dacl, index, &raw_ace) || raw_ace == nullptr) {
      unexpected_ace = true;
      continue;
    }
    const auto* header = static_cast<ACE_HEADER*>(raw_ace);
    if (header->AceType != ACCESS_ALLOWED_ACE_TYPE) {
      unexpected_ace = true;
      continue;
    }
    const auto* ace = static_cast<ACCESS_ALLOWED_ACE*>(raw_ace);
    PSID sid = const_cast<DWORD*>(&ace->SidStart);
    const bool full = (ace->Mask & required_access) == required_access ||
        (ace->Mask & GENERIC_ALL) == GENERIC_ALL;
    if (EqualSid(sid, const_cast<BYTE*>(current_sid.data()))) {
      result.current_user_full_control = result.current_user_full_control || full;
    } else if (EqualSid(sid, const_cast<BYTE*>(system_sid.data()))) {
      result.system_full_control = result.system_full_control || full;
    } else {
      unexpected_ace = true;
    }
  }
  result.other_users_denied = !unexpected_ace &&
      result.current_user_full_control && result.system_full_control;
  return result;
}

SecurityInspection InspectNamedObject(
    const std::wstring& object,
    SE_OBJECT_TYPE type,
    ACCESS_MASK required_access) {
  PSECURITY_DESCRIPTOR descriptor = nullptr;
  PSID owner = nullptr;
  PACL dacl = nullptr;
  const DWORD status = GetNamedSecurityInfoW(
      const_cast<LPWSTR>(object.c_str()),
      type,
      OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
      &owner,
      nullptr,
      &dacl,
      nullptr,
      &descriptor);
  if (status != ERROR_SUCCESS) {
    return {};
  }
  const SecurityInspection result = InspectSecurityDescriptor(descriptor, required_access);
  LocalFree(descriptor);
  return result;
}

SecurityInspection InspectKernelHandle(HANDLE handle) {
  PSECURITY_DESCRIPTOR descriptor = nullptr;
  PSID owner = nullptr;
  PACL dacl = nullptr;
  const DWORD status = GetSecurityInfo(
      handle,
      SE_KERNEL_OBJECT,
      OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
      &owner,
      nullptr,
      &dacl,
      nullptr,
      &descriptor);
  if (status != ERROR_SUCCESS) {
    return {};
  }
  // Named-pipe generic rights are mapped to file-object specific rights when
  // the kernel object is created, so inspect the effective FILE_ALL_ACCESS mask.
  const SecurityInspection result = InspectSecurityDescriptor(descriptor, FILE_ALL_ACCESS);
  LocalFree(descriptor);
  return result;
}

bool SecurityIsExact(const SecurityInspection& inspection) {
  return inspection.protected_dacl && inspection.owner_current_user &&
      inspection.current_user_full_control && inspection.system_full_control &&
      inspection.other_users_denied;
}

bool ApplyProtectedSecurity(const std::wstring& object, bool inheritable) {
  PSECURITY_DESCRIPTOR descriptor = CreateSecurityDescriptor(inheritable);
  if (descriptor == nullptr) {
    return false;
  }
  PSID owner = nullptr;
  BOOL owner_defaulted = FALSE;
  PACL dacl = nullptr;
  BOOL present = FALSE;
  BOOL defaulted = FALSE;
  const bool got_security = GetSecurityDescriptorOwner(
      descriptor,
      &owner,
      &owner_defaulted) != FALSE && owner != nullptr &&
      GetSecurityDescriptorDacl(
          descriptor,
          &present,
          &dacl,
          &defaulted) != FALSE && present && dacl != nullptr;
  DWORD status = ERROR_INVALID_SECURITY_DESCR;
  if (got_security) {
    status = SetNamedSecurityInfoW(
        const_cast<LPWSTR>(object.c_str()),
        SE_FILE_OBJECT,
        OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION |
            PROTECTED_DACL_SECURITY_INFORMATION,
        owner,
        nullptr,
        dacl,
        nullptr);
  }
  LocalFree(descriptor);
  return status == ERROR_SUCCESS;
}

bool ApplyProtectedDirectoryDacl(const std::wstring& directory) {
  return ApplyProtectedSecurity(directory, true);
}

bool ApplyProtectedFileDacl(const std::wstring& file) {
  return ApplyProtectedSecurity(file, false);
}

bool EnsureSecureDirectory(const std::wstring& directory) {
  PSECURITY_DESCRIPTOR descriptor = CreateSecurityDescriptor(true);
  if (descriptor == nullptr) {
    return false;
  }
  SECURITY_ATTRIBUTES attributes{};
  attributes.nLength = sizeof(attributes);
  attributes.lpSecurityDescriptor = descriptor;
  attributes.bInheritHandle = FALSE;
  if (!CreateDirectoryW(directory.c_str(), &attributes)) {
    const DWORD error = GetLastError();
    if (error != ERROR_ALREADY_EXISTS) {
      LocalFree(descriptor);
      return false;
    }
  }
  LocalFree(descriptor);

  const DWORD attributes_value = GetFileAttributesW(directory.c_str());
  if (attributes_value == INVALID_FILE_ATTRIBUTES ||
      (attributes_value & FILE_ATTRIBUTE_DIRECTORY) == 0 ||
      (attributes_value & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
    return false;
  }
  if (!ApplyProtectedDirectoryDacl(directory)) {
    return false;
  }
  return SecurityIsExact(InspectNamedObject(directory, SE_FILE_OBJECT, FILE_ALL_ACCESS));
}

std::wstring SecureRuntimeDirectory() {
  PWSTR local_app_data = nullptr;
  if (FAILED(SHGetKnownFolderPath(FOLDERID_LocalAppData, KF_FLAG_DEFAULT, nullptr, &local_app_data))) {
    return {};
  }
  const std::wstring root(local_app_data);
  CoTaskMemFree(local_app_data);
  const std::wstring component = root + L"\\vscode-lsp-mcp";
  const std::wstring runtime = component + L"\\run";
  if (!EnsureSecureDirectory(component) || !EnsureSecureDirectory(runtime)) {
    return {};
  }
  return runtime;
}

HANDLE CreatePipeHandle(const std::shared_ptr<ServerState>& state, bool first_instance) {
  PSECURITY_DESCRIPTOR descriptor = CreateSecurityDescriptor(false);
  if (descriptor == nullptr) {
    return INVALID_HANDLE_VALUE;
  }
  SECURITY_ATTRIBUTES attributes{};
  attributes.nLength = sizeof(attributes);
  attributes.lpSecurityDescriptor = descriptor;
  attributes.bInheritHandle = FALSE;
  const DWORD open_mode = PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED |
      (first_instance ? FILE_FLAG_FIRST_PIPE_INSTANCE : 0);
  const DWORD pipe_mode = PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT |
      PIPE_REJECT_REMOTE_CLIENTS;
  HANDLE handle = CreateNamedPipeW(
      state->name.c_str(),
      open_mode,
      pipe_mode,
      state->max_instances,
      65'536,
      65'536,
      0,
      &attributes);
  LocalFree(descriptor);
  if (handle == INVALID_HANDLE_VALUE) {
    return handle;
  }
  if (!SecurityIsExact(InspectKernelHandle(handle))) {
    CloseHandle(handle);
    return INVALID_HANDLE_VALUE;
  }
  {
    std::lock_guard<std::mutex> lock(state->mutex);
    if (state->closed) {
      CloseHandle(handle);
      return INVALID_HANDLE_VALUE;
    }
    state->handles.insert(handle);
  }
  return handle;
}

void CloseTrackedHandle(const std::shared_ptr<ServerState>& server, HANDLE handle) {
  if (handle == INVALID_HANDLE_VALUE) {
    return;
  }
  bool owned = false;
  {
    std::lock_guard<std::mutex> lock(server->mutex);
    const auto found = server->handles.find(handle);
    if (found != server->handles.end()) {
      server->handles.erase(found);
      owned = true;
    }
    if (server->pending_first == handle) {
      server->pending_first = INVALID_HANDLE_VALUE;
    }
  }
  if (owned) {
    CancelIoEx(handle, nullptr);
    DisconnectNamedPipe(handle);
    CloseHandle(handle);
  }
}

void CloseServerState(const std::shared_ptr<ServerState>& state) {
  std::vector<HANDLE> handles;
  {
    std::lock_guard<std::mutex> lock(state->mutex);
    if (state->closed) {
      return;
    }
    state->closed = true;
    handles.assign(state->handles.begin(), state->handles.end());
    state->handles.clear();
    state->pending_first = INVALID_HANDLE_VALUE;
  }
  for (HANDLE handle : handles) {
    CancelIoEx(handle, nullptr);
    DisconnectNamedPipe(handle);
    CloseHandle(handle);
  }
}

void CloseConnectionState(const std::shared_ptr<ConnectionState>& state) {
  if (!state->closed.exchange(true)) {
    CloseTrackedHandle(state->server, state->handle);
    state->handle = INVALID_HANDLE_VALUE;
  }
}

bool OverlappedConnect(HANDLE handle) {
  OVERLAPPED operation{};
  operation.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
  if (operation.hEvent == nullptr) {
    return false;
  }
  BOOL connected = ConnectNamedPipe(handle, &operation);
  if (!connected) {
    const DWORD error = GetLastError();
    if (error == ERROR_PIPE_CONNECTED) {
      connected = TRUE;
    } else if (error == ERROR_IO_PENDING) {
      const DWORD wait = WaitForSingleObject(operation.hEvent, INFINITE);
      DWORD transferred = 0;
      connected = wait == WAIT_OBJECT_0 &&
          GetOverlappedResult(handle, &operation, &transferred, FALSE);
    }
  }
  CloseHandle(operation.hEvent);
  return connected != FALSE;
}

bool OverlappedRead(HANDLE handle, BYTE* data, DWORD size, DWORD* transferred, bool* eof) {
  OVERLAPPED operation{};
  operation.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
  if (operation.hEvent == nullptr) {
    return false;
  }
  BOOL success = ReadFile(handle, data, size, transferred, &operation);
  if (!success) {
    const DWORD error = GetLastError();
    if (error == ERROR_BROKEN_PIPE || error == ERROR_PIPE_NOT_CONNECTED) {
      *eof = true;
      CloseHandle(operation.hEvent);
      return true;
    }
    if (error == ERROR_IO_PENDING) {
      const DWORD wait = WaitForSingleObject(operation.hEvent, INFINITE);
      success = wait == WAIT_OBJECT_0 &&
          GetOverlappedResult(handle, &operation, transferred, FALSE);
      if (!success) {
        const DWORD final_error = GetLastError();
        if (final_error == ERROR_BROKEN_PIPE || final_error == ERROR_PIPE_NOT_CONNECTED) {
          *eof = true;
          success = TRUE;
        }
      }
    }
  }
  CloseHandle(operation.hEvent);
  return success != FALSE;
}

bool OverlappedWrite(HANDLE handle, const BYTE* data, DWORD size, DWORD* transferred) {
  OVERLAPPED operation{};
  operation.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
  if (operation.hEvent == nullptr) {
    return false;
  }
  BOOL success = WriteFile(handle, data, size, transferred, &operation);
  if (!success && GetLastError() == ERROR_IO_PENDING) {
    const DWORD wait = WaitForSingleObject(operation.hEvent, INFINITE);
    success = wait == WAIT_OBJECT_0 &&
        GetOverlappedResult(handle, &operation, transferred, FALSE);
  }
  CloseHandle(operation.hEvent);
  return success != FALSE;
}

void ServerFinalizer(napi_env, void* data, void*) {
  auto* wrap = static_cast<ServerWrap*>(data);
  CloseServerState(wrap->state);
  delete wrap;
}

void ConnectionFinalizer(napi_env, void* data, void*) {
  auto* wrap = static_cast<ConnectionWrap*>(data);
  CloseConnectionState(wrap->state);
  delete wrap;
}

ConnectionWrap* UnwrapConnection(napi_env env, napi_callback_info info, size_t argc, napi_value* args) {
  napi_value this_value;
  size_t actual = argc;
  if (napi_get_cb_info(env, info, &actual, args, &this_value, nullptr) != napi_ok) {
    return nullptr;
  }
  ConnectionWrap* wrap = nullptr;
  if (napi_unwrap(env, this_value, reinterpret_cast<void**>(&wrap)) != napi_ok) {
    return nullptr;
  }
  return wrap;
}

ServerWrap* UnwrapServer(napi_env env, napi_callback_info info, size_t argc, napi_value* args) {
  napi_value this_value;
  size_t actual = argc;
  if (napi_get_cb_info(env, info, &actual, args, &this_value, nullptr) != napi_ok) {
    return nullptr;
  }
  ServerWrap* wrap = nullptr;
  if (napi_unwrap(env, this_value, reinterpret_cast<void**>(&wrap)) != napi_ok) {
    return nullptr;
  }
  return wrap;
}

struct DedicatedWork {
  napi_threadsafe_function completion = nullptr;
  void (*execute)(napi_env, void*) = nullptr;
  void (*complete)(napi_env, napi_status, void*) = nullptr;
  void (*abandon)(void*) = nullptr;
};

struct AcceptWork : DedicatedWork {
  napi_deferred deferred = nullptr;
  std::shared_ptr<ServerState> state;
  HANDLE handle = INVALID_HANDLE_VALUE;
  std::string error;
};

struct ReadWork : DedicatedWork {
  napi_deferred deferred = nullptr;
  std::shared_ptr<ConnectionState> state;
  std::vector<BYTE> buffer;
  DWORD transferred = 0;
  bool eof = false;
  std::string error;
};

struct WriteWork : DedicatedWork {
  napi_deferred deferred = nullptr;
  std::shared_ptr<ConnectionState> state;
  std::vector<BYTE> buffer;
  std::string error;
};

void CompleteDedicatedWork(napi_env env, napi_value, void*, void* data) {
  auto* work = static_cast<DedicatedWork*>(data);
  if (env == nullptr) {
    work->abandon(data);
  } else {
    work->complete(env, napi_ok, data);
  }
}

unsigned __stdcall RunDedicatedWork(void* data) {
  auto* work = static_cast<DedicatedWork*>(data);
  work->execute(nullptr, work);
  const napi_threadsafe_function completion_handle = work->completion;
  const napi_status status = napi_call_threadsafe_function(
      completion_handle,
      work,
      napi_tsfn_nonblocking);
  napi_release_threadsafe_function(completion_handle, napi_tsfn_release);
  if (status != napi_ok) {
    work->abandon(work);
  }
  return 0;
}

bool QueueDedicatedWork(
    napi_env env,
    const char* name,
    DedicatedWork* work,
    void (*execute)(napi_env, void*),
    void (*complete)(napi_env, napi_status, void*),
    void (*abandon)(void*)) {
  napi_value resource_name;
  if (napi_create_string_utf8(env, name, NAPI_AUTO_LENGTH, &resource_name) != napi_ok) {
    return false;
  }
  work->execute = execute;
  work->complete = complete;
  work->abandon = abandon;
  if (napi_create_threadsafe_function(
          env,
          nullptr,
          nullptr,
          resource_name,
          1,
          1,
          nullptr,
          nullptr,
          nullptr,
          CompleteDedicatedWork,
          &work->completion) != napi_ok) {
    return false;
  }
  const uintptr_t thread_handle = _beginthreadex(
      nullptr,
      0,
      RunDedicatedWork,
      work,
      0,
      nullptr);
  if (thread_handle == 0) {
    napi_release_threadsafe_function(work->completion, napi_tsfn_abort);
    work->completion = nullptr;
    return false;
  }
  CloseHandle(reinterpret_cast<HANDLE>(thread_handle));
  return true;
}

napi_value RejectPromise(napi_env env, napi_deferred deferred, const std::string& message) {
  napi_value error_message;
  napi_value error;
  napi_create_string_utf8(env, message.c_str(), NAPI_AUTO_LENGTH, &error_message);
  napi_create_error(env, nullptr, error_message, &error);
  napi_reject_deferred(env, deferred, error);
  return nullptr;
}

napi_value ConnectionRead(napi_env env, napi_callback_info info);
napi_value ConnectionWrite(napi_env env, napi_callback_info info);
napi_value ConnectionClose(napi_env env, napi_callback_info info);

napi_value CreateConnectionObject(
    napi_env env,
    const std::shared_ptr<ServerState>& server,
    HANDLE handle) {
  napi_value object;
  if (napi_create_object(env, &object) != napi_ok) {
    return nullptr;
  }
  auto state = std::make_shared<ConnectionState>();
  state->server = server;
  state->handle = handle;
  auto* wrap = new ConnectionWrap{state};
  if (napi_wrap(env, object, wrap, ConnectionFinalizer, nullptr, nullptr) != napi_ok) {
    delete wrap;
    return nullptr;
  }
  const napi_property_descriptor properties[] = {
      {"read", nullptr, ConnectionRead, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"write", nullptr, ConnectionWrite, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"close", nullptr, ConnectionClose, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  if (napi_define_properties(
          env,
          object,
          sizeof(properties) / sizeof(properties[0]),
          properties) != napi_ok) {
    return nullptr;
  }
  return object;
}

void ExecuteAccept(napi_env, void* data) {
  auto* work = static_cast<AcceptWork*>(data);
  {
    std::lock_guard<std::mutex> lock(work->state->mutex);
    if (work->state->closed) {
      work->error = "Secure pipe server is closed.";
      return;
    }
    if (work->state->pending_first != INVALID_HANDLE_VALUE) {
      work->handle = work->state->pending_first;
      work->state->pending_first = INVALID_HANDLE_VALUE;
    } else if (work->state->handles.size() >= work->state->max_instances) {
      work->error = "Secure pipe server reached its instance limit.";
      return;
    }
  }
  if (work->handle == INVALID_HANDLE_VALUE) {
    work->handle = CreatePipeHandle(work->state, false);
  }
  if (work->handle == INVALID_HANDLE_VALUE || !OverlappedConnect(work->handle)) {
    if (work->handle != INVALID_HANDLE_VALUE) {
      CloseTrackedHandle(work->state, work->handle);
    }
    work->handle = INVALID_HANDLE_VALUE;
    work->error = "Secure pipe accept failed.";
  }
}

void CompleteAccept(napi_env env, napi_status status, void* data) {
  auto* work = static_cast<AcceptWork*>(data);
  if (status != napi_ok || !work->error.empty()) {
    RejectPromise(env, work->deferred, work->error.empty() ? "Secure pipe accept failed." : work->error);
  } else {
    napi_value connection = CreateConnectionObject(env, work->state, work->handle);
    if (connection == nullptr) {
      CloseTrackedHandle(work->state, work->handle);
      RejectPromise(env, work->deferred, "Unable to create secure pipe connection.");
    } else {
      napi_resolve_deferred(env, work->deferred, connection);
    }
  }
  delete work;
}

void AbandonAccept(void* data) {
  auto* work = static_cast<AcceptWork*>(data);
  if (work->handle != INVALID_HANDLE_VALUE) {
    CloseTrackedHandle(work->state, work->handle);
  }
  delete work;
}

napi_value ServerAccept(napi_env env, napi_callback_info info) {
  ServerWrap* wrap = UnwrapServer(env, info, 0, nullptr);
  if (wrap == nullptr) {
    ThrowLastError(env, "Invalid secure pipe server.");
    return nullptr;
  }
  auto* work = new AcceptWork();
  work->state = wrap->state;
  napi_value promise;
  napi_create_promise(env, &work->deferred, &promise);
  if (!QueueDedicatedWork(
          env,
          "securePipeAccept",
          work,
          ExecuteAccept,
          CompleteAccept,
          AbandonAccept)) {
    delete work;
    ThrowLastError(env, "Unable to queue secure pipe accept.");
    return nullptr;
  }
  return promise;
}

napi_value ServerClose(napi_env env, napi_callback_info info) {
  ServerWrap* wrap = UnwrapServer(env, info, 0, nullptr);
  if (wrap != nullptr) {
    CloseServerState(wrap->state);
  }
  napi_value undefined;
  napi_get_undefined(env, &undefined);
  return undefined;
}

napi_value SecurityInspectionObject(
    napi_env env,
    const SecurityInspection& inspection,
    DWORD max_instances) {
  napi_value result;
  if (napi_create_object(env, &result) != napi_ok ||
      !SetBoolean(env, result, "protectedDacl", inspection.protected_dacl) ||
      !SetBoolean(env, result, "ownerCurrentUser", inspection.owner_current_user) ||
      !SetBoolean(env, result, "currentUserFullControl", inspection.current_user_full_control) ||
      !SetBoolean(env, result, "systemFullControl", inspection.system_full_control) ||
      !SetBoolean(env, result, "otherUsersDenied", inspection.other_users_denied) ||
      !SetBoolean(env, result, "remoteClientsRejected", true) ||
      !SetBoolean(env, result, "byteMode", true) ||
      !SetBoolean(env, result, "firstInstance", true) ||
      !SetInteger(env, result, "maxInstances", static_cast<int32_t>(max_instances))) {
    return nullptr;
  }
  return result;
}

napi_value ServerInspectSecurity(napi_env env, napi_callback_info info) {
  ServerWrap* wrap = UnwrapServer(env, info, 0, nullptr);
  if (wrap == nullptr) {
    ThrowLastError(env, "Invalid secure pipe server.");
    return nullptr;
  }
  HANDLE handle = INVALID_HANDLE_VALUE;
  {
    std::lock_guard<std::mutex> lock(wrap->state->mutex);
    if (!wrap->state->handles.empty()) {
      handle = *wrap->state->handles.begin();
    }
  }
  if (handle == INVALID_HANDLE_VALUE) {
    ThrowLastError(env, "Secure pipe server has no inspectable handle.");
    return nullptr;
  }
  napi_value result = SecurityInspectionObject(
      env,
      InspectKernelHandle(handle),
      wrap->state->max_instances);
  if (result == nullptr) {
    ThrowLastError(env, "Unable to inspect secure pipe security.");
  }
  return result;
}

void ExecuteRead(napi_env, void* data) {
  auto* work = static_cast<ReadWork*>(data);
  if (work->state->closed || work->state->handle == INVALID_HANDLE_VALUE) {
    work->error = "Secure pipe connection is closed.";
    return;
  }
  if (!OverlappedRead(
          work->state->handle,
          work->buffer.data(),
          static_cast<DWORD>(work->buffer.size()),
          &work->transferred,
          &work->eof)) {
    work->error = "Secure pipe read failed.";
  }
}

void CompleteRead(napi_env env, napi_status status, void* data) {
  auto* work = static_cast<ReadWork*>(data);
  work->state->read_pending = false;
  if (status != napi_ok || !work->error.empty()) {
    RejectPromise(env, work->deferred, work->error.empty() ? "Secure pipe read failed." : work->error);
  } else if (work->eof) {
    napi_value null_value;
    napi_get_null(env, &null_value);
    napi_resolve_deferred(env, work->deferred, null_value);
  } else {
    napi_value buffer;
    void* copied = nullptr;
    if (napi_create_buffer_copy(
            env,
            work->transferred,
            work->buffer.data(),
            &copied,
            &buffer) != napi_ok) {
      RejectPromise(env, work->deferred, "Unable to create secure pipe read buffer.");
    } else {
      napi_resolve_deferred(env, work->deferred, buffer);
    }
  }
  delete work;
}

void AbandonRead(void* data) {
  auto* work = static_cast<ReadWork*>(data);
  work->state->read_pending = false;
  delete work;
}

napi_value ConnectionRead(napi_env env, napi_callback_info info) {
  napi_value args[1] = {nullptr};
  ConnectionWrap* wrap = UnwrapConnection(env, info, 1, args);
  if (wrap == nullptr || wrap->state->read_pending.exchange(true)) {
    ThrowLastError(env, "Secure pipe allows only one pending read.");
    return nullptr;
  }
  uint32_t maximum = 65'536;
  napi_valuetype type = napi_undefined;
  if (args[0] != nullptr && napi_typeof(env, args[0], &type) == napi_ok && type != napi_undefined) {
    if (napi_get_value_uint32(env, args[0], &maximum) != napi_ok ||
        maximum < 1 || maximum > 16'777'216) {
      wrap->state->read_pending = false;
      ThrowLastError(env, "Secure pipe read size is invalid.");
      return nullptr;
    }
  }
  auto* work = new ReadWork();
  work->state = wrap->state;
  work->buffer.resize(maximum);
  napi_value promise;
  napi_create_promise(env, &work->deferred, &promise);
  if (!QueueDedicatedWork(
          env,
          "securePipeRead",
          work,
          ExecuteRead,
          CompleteRead,
          AbandonRead)) {
    wrap->state->read_pending = false;
    delete work;
    ThrowLastError(env, "Unable to queue secure pipe read.");
    return nullptr;
  }
  return promise;
}

void ExecuteWrite(napi_env, void* data) {
  auto* work = static_cast<WriteWork*>(data);
  if (work->state->closed || work->state->handle == INVALID_HANDLE_VALUE) {
    work->error = "Secure pipe connection is closed.";
    return;
  }
  size_t offset = 0;
  while (offset < work->buffer.size()) {
    const DWORD remaining = static_cast<DWORD>(std::min<size_t>(
        work->buffer.size() - offset,
        static_cast<size_t>(MAXDWORD)));
    DWORD transferred = 0;
    if (!OverlappedWrite(
            work->state->handle,
            work->buffer.data() + offset,
            remaining,
            &transferred) || transferred == 0) {
      work->error = "Secure pipe write failed.";
      return;
    }
    offset += transferred;
  }
}

void CompleteWrite(napi_env env, napi_status status, void* data) {
  auto* work = static_cast<WriteWork*>(data);
  work->state->write_pending = false;
  if (status != napi_ok || !work->error.empty()) {
    RejectPromise(env, work->deferred, work->error.empty() ? "Secure pipe write failed." : work->error);
  } else {
    napi_value undefined;
    napi_get_undefined(env, &undefined);
    napi_resolve_deferred(env, work->deferred, undefined);
  }
  delete work;
}

void AbandonWrite(void* data) {
  auto* work = static_cast<WriteWork*>(data);
  work->state->write_pending = false;
  delete work;
}

napi_value ConnectionWrite(napi_env env, napi_callback_info info) {
  napi_value args[1] = {nullptr};
  ConnectionWrap* wrap = UnwrapConnection(env, info, 1, args);
  if (wrap == nullptr || wrap->state->write_pending.exchange(true)) {
    ThrowLastError(env, "Secure pipe allows only one pending write.");
    return nullptr;
  }
  bool is_buffer = false;
  void* bytes = nullptr;
  size_t length = 0;
  if (args[0] == nullptr ||
      napi_is_buffer(env, args[0], &is_buffer) != napi_ok ||
      !is_buffer ||
      napi_get_buffer_info(env, args[0], &bytes, &length) != napi_ok ||
      length < 1 || length > 16'777'220) {
    wrap->state->write_pending = false;
    ThrowLastError(env, "Secure pipe write payload is invalid.");
    return nullptr;
  }
  auto* work = new WriteWork();
  work->state = wrap->state;
  const auto* begin = static_cast<const BYTE*>(bytes);
  work->buffer.assign(begin, begin + length);
  napi_value promise;
  napi_create_promise(env, &work->deferred, &promise);
  if (!QueueDedicatedWork(
          env,
          "securePipeWrite",
          work,
          ExecuteWrite,
          CompleteWrite,
          AbandonWrite)) {
    wrap->state->write_pending = false;
    delete work;
    ThrowLastError(env, "Unable to queue secure pipe write.");
    return nullptr;
  }
  return promise;
}

napi_value ConnectionClose(napi_env env, napi_callback_info info) {
  ConnectionWrap* wrap = UnwrapConnection(env, info, 0, nullptr);
  if (wrap != nullptr) {
    CloseConnectionState(wrap->state);
  }
  napi_value undefined;
  napi_get_undefined(env, &undefined);
  return undefined;
}

napi_value GetBuildInfo(napi_env env, napi_callback_info) {
  napi_value result;
  if (napi_create_object(env, &result) != napi_ok ||
      !SetString(env, result, "abi", "node-api") ||
      !SetInteger(env, result, "napiVersion", NAPI_VERSION) ||
      !SetString(env, result, "targetArch", TargetArchitecture()) ||
      !SetBoolean(env, result, "securityOperationsImplemented", true)) {
    ThrowLastError(env, "Unable to create native build information.");
    return nullptr;
  }
  return result;
}

napi_value EnsureSecureRuntimeDirectory(napi_env env, napi_callback_info) {
  const std::wstring directory = SecureRuntimeDirectory();
  const auto current_sid = CurrentUserSid();
  if (directory.empty() || current_sid.empty()) {
    ThrowLastError(env, "Unable to establish secure Windows runtime directory.");
    return nullptr;
  }
  const SecurityInspection inspection = InspectNamedObject(
      directory,
      SE_FILE_OBJECT,
      FILE_ALL_ACCESS);
  if (!SecurityIsExact(inspection)) {
    ThrowLastError(env, "Windows runtime directory security verification failed.");
    return nullptr;
  }
  napi_value result;
  if (napi_create_object(env, &result) != napi_ok ||
      !SetWideString(env, result, "path", directory) ||
      !SetWideString(
          env,
          result,
          "currentUserSid",
          SidString(const_cast<BYTE*>(current_sid.data()))) ||
      !SetBoolean(env, result, "protectedDacl", inspection.protected_dacl) ||
      !SetBoolean(env, result, "reparsePoint", false) ||
      !SetBoolean(env, result, "ownerCurrentUser", inspection.owner_current_user) ||
      !SetBoolean(env, result, "systemFullControl", inspection.system_full_control) ||
      !SetBoolean(env, result, "otherUsersDenied", inspection.other_users_denied)) {
    ThrowLastError(env, "Unable to return secure Windows runtime directory information.");
    return nullptr;
  }
  return result;
}

napi_value VerifySecureRegistryFile(napi_env env, napi_callback_info info) {
  napi_value args[1];
  size_t argc = 1;
  napi_value this_value;
  if (napi_get_cb_info(env, info, &argc, args, &this_value, nullptr) != napi_ok || argc != 1) {
    ThrowLastError(env, "Registry path is required.");
    return nullptr;
  }
  std::wstring file;
  if (!GetWideString(env, args[0], &file) || file.empty()) {
    ThrowLastError(env, "Registry path is invalid.");
    return nullptr;
  }
  const DWORD attributes = GetFileAttributesW(file.c_str());
  bool secure = attributes != INVALID_FILE_ATTRIBUTES &&
      (attributes & FILE_ATTRIBUTE_DIRECTORY) == 0 &&
      (attributes & FILE_ATTRIBUTE_REPARSE_POINT) == 0;
  if (secure) {
    SecurityInspection inspection = InspectNamedObject(file, SE_FILE_OBJECT, FILE_ALL_ACCESS);
    if (!SecurityIsExact(inspection)) {
      secure = ApplyProtectedFileDacl(file);
      inspection = InspectNamedObject(file, SE_FILE_OBJECT, FILE_ALL_ACCESS);
    }
    secure = secure && SecurityIsExact(inspection);
  }
  napi_value result;
  napi_get_boolean(env, secure, &result);
  return result;
}

napi_value CreateSecurePipeServer(napi_env env, napi_callback_info info) {
  napi_value args[1];
  size_t argc = 1;
  napi_value this_value;
  if (napi_get_cb_info(env, info, &argc, args, &this_value, nullptr) != napi_ok || argc != 1) {
    ThrowLastError(env, "Secure pipe options are required.");
    return nullptr;
  }
  napi_value name_value;
  napi_value max_value;
  if (napi_get_named_property(env, args[0], "name", &name_value) != napi_ok ||
      napi_get_named_property(env, args[0], "maxInstances", &max_value) != napi_ok) {
    ThrowLastError(env, "Secure pipe options are invalid.");
    return nullptr;
  }
  std::wstring name;
  uint32_t max_instances = 0;
  if (!GetWideString(env, name_value, &name) ||
      name.rfind(L"\\\\.\\pipe\\vscode-lsp-mcp-", 0) != 0 ||
      name.size() > 240 ||
      napi_get_value_uint32(env, max_value, &max_instances) != napi_ok ||
      max_instances < 1 || max_instances > 4) {
    ThrowLastError(env, "Secure pipe options are invalid.");
    return nullptr;
  }
  auto state = std::make_shared<ServerState>();
  state->name = name;
  state->max_instances = max_instances;
  const HANDLE first = CreatePipeHandle(state, true);
  if (first == INVALID_HANDLE_VALUE) {
    ThrowLastError(env, "Unable to create first secure pipe instance.");
    return nullptr;
  }
  {
    std::lock_guard<std::mutex> lock(state->mutex);
    state->pending_first = first;
  }

  napi_value server;
  if (napi_create_object(env, &server) != napi_ok) {
    CloseServerState(state);
    return nullptr;
  }
  auto* wrap = new ServerWrap{state};
  if (napi_wrap(env, server, wrap, ServerFinalizer, nullptr, nullptr) != napi_ok) {
    CloseServerState(state);
    delete wrap;
    return nullptr;
  }
  const napi_property_descriptor properties[] = {
      {"accept", nullptr, ServerAccept, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"close", nullptr, ServerClose, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"inspectSecurity", nullptr, ServerInspectSecurity, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  if (napi_define_properties(
          env,
          server,
          sizeof(properties) / sizeof(properties[0]),
          properties) != napi_ok) {
    CloseServerState(state);
    return nullptr;
  }
  return server;
}

napi_value Initialize(napi_env env, napi_value exports) {
  const napi_property_descriptor properties[] = {
      {"getBuildInfo", nullptr, GetBuildInfo, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"ensureSecureRuntimeDirectory", nullptr, EnsureSecureRuntimeDirectory, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"verifySecureRegistryFile", nullptr, VerifySecureRegistryFile, nullptr, nullptr, nullptr, napi_default, nullptr},
      {"createSecurePipeServer", nullptr, CreateSecurePipeServer, nullptr, nullptr, nullptr, napi_default, nullptr},
  };
  if (napi_define_properties(
          env,
          exports,
          sizeof(properties) / sizeof(properties[0]),
          properties) != napi_ok) {
    ThrowLastError(env, "Unable to initialize native Windows security adapter.");
    return nullptr;
  }
  return exports;
}

}  // namespace

NAPI_MODULE(NODE_GYP_MODULE_NAME, Initialize)
