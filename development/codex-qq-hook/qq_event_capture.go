package main

import (
	"bytes"
	"crypto/ed25519"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const maxCallbackBodyBytes int64 = 1 << 20

type payload struct {
	Op int             `json:"op"`
	T  string          `json:"t"`
	S  *int            `json:"s,omitempty"`
	D  json.RawMessage `json:"d"`
}

type validationRequest struct {
	PlainToken string `json:"plain_token"`
	EventTs    string `json:"event_ts"`
}

type validationResponse struct {
	PlainToken string `json:"plain_token"`
	Signature  string `json:"signature"`
}

type captureRecord struct {
	Time      string            `json:"time"`
	Remote    string            `json:"remote"`
	EventType string            `json:"event_type"`
	Extracted map[string]string `json:"extracted"`
	Raw       json.RawMessage   `json:"raw"`
}

func main() {
	addr := flag.String("addr", "127.0.0.1:8080", "listen address")
	logFile := flag.String("log", defaultLogFile(), "jsonl log file")
	flag.Parse()

	secret := os.Getenv("QQ_BOT_APP_SECRET")
	if secret == "" {
		log.Fatal("missing QQ_BOT_APP_SECRET")
	}

	if err := os.MkdirAll(filepath.Dir(*logFile), 0755); err != nil {
		log.Fatalf("create log dir: %v", err)
	}
	f, err := os.OpenFile(*logFile, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0600)
	if err != nil {
		log.Fatalf("open log file: %v", err)
	}
	defer f.Close()

	publicKey, privateKey := botKeys(secret)
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		handleCallback(w, r, publicKey, privateKey, f)
	})

	log.Printf("QQ event capture listening on %s", *addr)
	log.Printf("Webhook path: /")
	log.Printf("Log file: %s", *logFile)
	log.Printf("After configuring the public HTTPS URL in q.qq.com, send a private message to the bot or @ it in a group.")

	server := &http.Server{
		Addr:              *addr,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       60 * time.Second,
		MaxHeaderBytes:    1 << 20,
	}
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}

func defaultLogFile() string {
	host, err := os.Hostname()
	if err != nil || host == "" {
		host = "host"
	}
	name := fmt.Sprintf("qq_openid_capture_%s_%s.jsonl", sanitize(host), time.Now().Format("20060102_150405"))
	return filepath.Join("runtimeLogs", name)
}

func sanitize(s string) string {
	replacer := strings.NewReplacer(" ", "_", "\\", "_", "/", "_", ":", "_", "*", "_", "?", "_", "\"", "_", "<", "_", ">", "_", "|", "_")
	return replacer.Replace(s)
}

func botKeys(secret string) (public ed25519.PublicKey, private ed25519.PrivateKey) {
	seed := secret
	for len(seed) < ed25519.SeedSize {
		seed = strings.Repeat(seed, 2)
	}
	reader := strings.NewReader(seed[:ed25519.SeedSize])
	public, private, err := ed25519.GenerateKey(reader)
	if err != nil {
		log.Fatalf("generate ed25519 key: %v", err)
	}
	return public, private
}

func handleCallback(w http.ResponseWriter, r *http.Request, publicKey ed25519.PublicKey, privateKey ed25519.PrivateKey, logFile *os.File) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	r.Body = http.MaxBytesReader(w, r.Body, maxCallbackBodyBytes)
	body, err := io.ReadAll(r.Body)
	if err != nil {
		var maxBytesError *http.MaxBytesError
		if errors.As(err, &maxBytesError) {
			http.Error(w, "request body too large", http.StatusRequestEntityTooLarge)
			return
		}
		http.Error(w, "read body failed", http.StatusBadRequest)
		return
	}

	var p payload
	if err := json.Unmarshal(body, &p); err != nil {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}

	if p.Op == 13 {
		handleValidation(w, p, privateKey)
		return
	}

	if !skipSignatureVerify() && !verifySignature(r, body, publicKey) {
		http.Error(w, "invalid signature", http.StatusUnauthorized)
		return
	}

	extracted := extractIDs(p)
	record := captureRecord{
		Time:      time.Now().Format(time.RFC3339),
		Remote:    r.RemoteAddr,
		EventType: p.T,
		Extracted: extracted,
		Raw:       json.RawMessage(append([]byte(nil), body...)),
	}
	writeRecord(logFile, record)
	printExtracted(record)

	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write([]byte(`{"ok":true}`))
}

func handleValidation(w http.ResponseWriter, p payload, privateKey ed25519.PrivateKey) {
	var req validationRequest
	if err := json.Unmarshal(p.D, &req); err != nil {
		http.Error(w, "invalid validation payload", http.StatusBadRequest)
		return
	}
	msg := []byte(req.EventTs + req.PlainToken)
	resp := validationResponse{
		PlainToken: req.PlainToken,
		Signature:  hex.EncodeToString(ed25519.Sign(privateKey, msg)),
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}

func verifySignature(r *http.Request, body []byte, publicKey ed25519.PublicKey) bool {
	signature := r.Header.Get("X-Signature-Ed25519")
	timestamp := r.Header.Get("X-Signature-Timestamp")
	if signature == "" || timestamp == "" {
		log.Printf("missing signature headers")
		return false
	}
	sig, err := hex.DecodeString(signature)
	if err != nil {
		log.Printf("decode signature: %v", err)
		return false
	}
	if len(sig) != ed25519.SignatureSize || sig[63]&224 != 0 {
		log.Printf("invalid signature size or format")
		return false
	}
	msg := bytes.NewBufferString(timestamp)
	msg.Write(body)
	return ed25519.Verify(publicKey, msg.Bytes(), sig)
}

func skipSignatureVerify() bool {
	v := strings.ToLower(strings.TrimSpace(os.Getenv("QQ_BOT_SKIP_SIGNATURE_VERIFY")))
	return v == "1" || v == "true" || v == "yes" || v == "on"
}

func extractIDs(p payload) map[string]string {
	out := map[string]string{}
	var d map[string]any
	if err := json.Unmarshal(p.D, &d); err != nil {
		return out
	}

	putString(out, "event_type", p.T)
	putPath(out, d, "QQ_BOT_OPENID", "author", "user_openid")
	putPath(out, d, "QQ_BOT_GROUP_OPENID", "group_openid")
	putPath(out, d, "QQ_BOT_MEMBER_OPENID", "author", "member_openid")
	putPath(out, d, "QQ_BOT_CHANNEL_ID", "channel_id")
	putPath(out, d, "QQ_BOT_GUILD_ID", "guild_id")
	putPath(out, d, "QQ_BOT_MSG_ID", "id")
	putPath(out, d, "content", "content")
	return out
}

func putPath(out map[string]string, root map[string]any, key string, path ...string) {
	var cur any = root
	for _, part := range path {
		m, ok := cur.(map[string]any)
		if !ok {
			return
		}
		cur = m[part]
	}
	if s, ok := cur.(string); ok && s != "" {
		putString(out, key, s)
	}
}

func putString(out map[string]string, key, value string) {
	if value != "" {
		out[key] = value
	}
}

func writeRecord(f *os.File, record captureRecord) {
	data, err := json.Marshal(record)
	if err != nil {
		log.Printf("marshal capture record: %v", err)
		return
	}
	if _, err := f.Write(append(data, '\n')); err != nil {
		log.Printf("write capture log: %v", err)
	}
}

func printExtracted(record captureRecord) {
	fmt.Println("---- QQ event captured ----")
	fmt.Printf("event_type=%s\n", record.EventType)
	keys := make([]string, 0, len(record.Extracted))
	for key := range record.Extracted {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		fmt.Printf("%s=%s\n", key, record.Extracted[key])
	}
	fmt.Println("---------------------------")
}
