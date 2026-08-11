package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

func newCaptureFile(t *testing.T) *os.File {
	t.Helper()
	file, err := os.CreateTemp(t.TempDir(), "capture-*.jsonl")
	if err != nil {
		t.Fatalf("create capture file: %v", err)
	}
	t.Cleanup(func() { _ = file.Close() })
	return file
}

func TestHandleCallbackRejectsNonPost(t *testing.T) {
	publicKey, privateKey := botKeys("test-secret")
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, "/", nil)
	handleCallback(recorder, request, publicKey, privateKey, newCaptureFile(t))
	if recorder.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusMethodNotAllowed)
	}
}

func TestHandleCallbackRejectsOversizedBody(t *testing.T) {
	publicKey, privateKey := botKeys("test-secret")
	logFile := newCaptureFile(t)
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(strings.Repeat("x", int(maxCallbackBodyBytes)+1)))
	handleCallback(recorder, request, publicKey, privateKey, logFile)
	if recorder.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusRequestEntityTooLarge)
	}
	info, err := logFile.Stat()
	if err != nil {
		t.Fatalf("stat capture file: %v", err)
	}
	if info.Size() != 0 {
		t.Fatalf("oversized request wrote %d bytes", info.Size())
	}
}

func TestHandleCallbackCapturesBoundedEvent(t *testing.T) {
	t.Setenv("QQ_BOT_SKIP_SIGNATURE_VERIFY", "true")
	publicKey, privateKey := botKeys("test-secret")
	logFile := newCaptureFile(t)
	body := `{"op":0,"t":"C2C_MESSAGE_CREATE","d":{"author":{"user_openid":"openid-a"},"content":"hello"}}`
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(body))
	handleCallback(recorder, request, publicKey, privateKey, logFile)
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusOK)
	}
	if err := logFile.Sync(); err != nil {
		t.Fatalf("sync capture file: %v", err)
	}
	data, err := os.ReadFile(logFile.Name())
	if err != nil {
		t.Fatalf("read capture file: %v", err)
	}
	var record captureRecord
	if err := json.Unmarshal(data, &record); err != nil {
		t.Fatalf("decode capture record: %v", err)
	}
	if record.Extracted["QQ_BOT_OPENID"] != "openid-a" {
		t.Fatalf("openid = %q", record.Extracted["QQ_BOT_OPENID"])
	}
}

func TestHandleCallbackValidation(t *testing.T) {
	publicKey, privateKey := botKeys("test-secret")
	recorder := httptest.NewRecorder()
	body := `{"op":13,"d":{"plain_token":"plain","event_ts":"123"}}`
	request := httptest.NewRequest(http.MethodPost, "/", strings.NewReader(body))
	handleCallback(recorder, request, publicKey, privateKey, newCaptureFile(t))
	if recorder.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", recorder.Code, http.StatusOK)
	}
	var response validationResponse
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatalf("decode validation response: %v", err)
	}
	if response.PlainToken != "plain" || response.Signature == "" {
		t.Fatalf("unexpected validation response: %+v", response)
	}
}
